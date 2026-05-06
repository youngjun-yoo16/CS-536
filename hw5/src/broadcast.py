
# Broadcast algorithms
#
# Broadcast: the root process has some data, and after the
# operation every process has a copy of that data.

import torch
import torch.distributed as dist
import math


def BcBinaryTree(tensor, worldSize, rank, root=0):
    # Binary Tree Broadcast:
    # lay out all ranks as a binary tree:
    #   node i's left child  = 2*i + 1
    #   node i's right child = 2*i + 2
    #   node i's parent      = (i-1) // 2
    #
    # the root sends to its 2 children, each of them forwards to
    # their 2 children, etc. Tree depth is ceil(log2(N)).
    #
    # the nice thing is each node only does at most 1 recv + 2 sends.
    # downside: in the first step only 2 links are active so startup is slow.

    result = tensor.clone()

    if worldSize == 1:
        return result

    # remap ranks so that `root` sits at position 0 in the tree
    # this way the tree logic always works from "tree rank 0" as root
    def toTreeRank(r):
        return (r - root) % worldSize

    def fromTreeRank(tr):
        return (tr + root) % worldSize

    treeRank = toTreeRank(rank)

    # figure out where we sit in the tree
    if treeRank == 0:
        parent = -1            # we're the root, no parent
    else:
        parent = (treeRank - 1) // 2

    leftChild = 2 * treeRank + 1
    rightChild = 2 * treeRank + 2

    # step 1: if we're not root, wait to get data from our parent
    if parent >= 0:
        parentActual = fromTreeRank(parent)
        dist.recv(result, src=parentActual)

    # step 2: forward to our children (if they exist)
    if leftChild < worldSize:
        leftActual = fromTreeRank(leftChild)
        dist.send(result, dst=leftActual)

    if rightChild < worldSize:
        rightActual = fromTreeRank(rightChild)
        dist.send(result, dst=rightActual)

    return result


def BcBinomialTree(tensor, worldSize, rank, root=0):
    # Binomial Tree Broadcast:
    # works in ceil(log2(N)) steps, going from the biggest power-of-2
    # distance down to 1.
    #
    # step k (high to low): every process that already has data AND
    # whose relativeRank is divisible by 2^(k+1) sends to
    # relativeRank + 2^k.
    #
    # example with 4 processes:
    #   step 1 (k=1): rank 0 -> rank 2          (distance 2)
    #   step 0 (k=0): rank 0 -> rank 1          (distance 1)
    #                  rank 2 -> rank 3          (distance 1)
    #
    # so two processes get data in step 1, then two more in step 0.
    # this has lower latency than binary tree because in step 0 two
    # sends happen in parallel.

    result = tensor.clone()

    if worldSize == 1:
        return result

    # shift all ranks so root becomes "relative rank 0"
    relativeRank = (rank - root) % worldSize
    numSteps = int(math.ceil(math.log2(worldSize)))

    # figure out WHEN this process receives data
    # rank 0 already has it. for others, the receive step equals
    # the position of the lowest set bit in relativeRank.
    # e.g. rank 2 = 0b10 -> lowest bit at pos 1 -> receives at step 1
    #      rank 3 = 0b11 -> lowest bit at pos 0 -> receives at step 0
    #      rank 1 = 0b01 -> lowest bit at pos 0 -> receives at step 0
    if relativeRank == 0:
        receiveStep = -1  # root — already has data
    else:
        # (x & -x) isolates the lowest set bit, bit_length()-1 gives its position
        receiveStep = (relativeRank & -relativeRank).bit_length() - 1

    # go through steps from highest to lowest
    for step in range(numSteps - 1, -1, -1):
        if relativeRank == 0 or (receiveStep >= 0 and step < receiveStep):
            # we already have data — check if we should send at this step.
            # we send if our relativeRank is aligned to 2^(step+1),
            # meaning we're the "lead" sender for this step's group.
            if relativeRank % (1 << (step + 1)) == 0:
                targetRelative = relativeRank + (1 << step)
                if targetRelative < worldSize:
                    targetActual = (targetRelative + root) % worldSize
                    dist.send(result, dst=targetActual)
        elif step == receiveStep:
            # this is the step where we finally get our data
            # sender is us minus 2^step (our "parent" in the binomial tree)
            senderRelative = relativeRank - (1 << step)
            senderActual = (senderRelative + root) % worldSize
            dist.recv(result, src=senderActual)
        # else: we don't have data yet and it's not our turn — just wait

    return result
