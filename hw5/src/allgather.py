# AllGather algorithms
#
# AllGather: every process starts with one chunk of data.
# After the operation, every process has ALL chunks from everyone.
# So if there are N procs, the output is N times bigger than input.
# We implement 3 different algorithms for AllGather, each with different
# communication patterns and tradeoffs.

import torch
import torch.distributed as dist
import math


def AllRing(sendTensor, gpSize, rank):
    # Ring AllGather:
    # Imagine all processes sitting in a circle. Each step, everyone
    # passes what they have to the right and receives from the left.
    # After (gpSize - 1) steps, everyone has seen every chunk.
    #
    # pros: simple, bandwidth-optimal for large messages
    # cons: latency is O(N) steps which hurts for small messages

    # chunkSize = number of elements in each process's input tensor
    chunkSize = sendTensor.numel()

    # result buffer to hold all chunks (gpSize total)
    result = torch.zeros(chunkSize * gpSize, dtype=sendTensor.dtype)

    # start with just our own chunk in the right spot in the result
    # rank*chunkSize : start of our chunk, (rank+1)*chunkSize : end of our chunk
    # we clone to make sure it's not a view into the sendTensor, since we'll overwrite result in-place as we go
    result[rank * chunkSize:(rank + 1) * chunkSize] = sendTensor.clone()

    # what we're about to send (starts as our own data)
    # we clone to make sure it's not a view into result, since we'll overwrite result in-place as we go
    # we'll update this each step to be the chunk we just received, which we then forward on the next step
    sendBuf = sendTensor.clone()
    recvBuf = torch.zeros_like(sendTensor)

    # neighbors in the ring
    # we receive from left, send to right. Modulo wraps around the ends of the ring.
    left = (rank - 1) % gpSize   # who we receive from
    right = (rank + 1) % gpSize  # who we send to


    # each step, send what we have to the right and receive from the left
    # after gpSize-1 steps, everyone has everything because the data has gone all the way around the ring
    # we have to do gpSize-1 steps because we start with our own chunk already in place, so we only need to receive the other gpSize-1 chunks
    for step in range(gpSize - 1):
        # send what we have to the right, receive from the left
        sendReq = dist.isend(sendBuf, dst=right)
        recvReq = dist.irecv(recvBuf, src=left)

        # wait for both to complete before we can read recvBuf and update result
        sendReq.wait()
        recvReq.wait()

        # figure out which rank originally owned the chunk we just got
        # it's been forwarded (step+1) times around the ring to reach us
        sourceRank = (rank - step - 1) % gpSize

        # place the received chunk into the right spot in result
        # sourceRank*chunkSize : start of that chunk, (sourceRank+1)*chunkSize : end of that chunk
        result[sourceRank * chunkSize:(sourceRank + 1) * chunkSize] = recvBuf.clone()

        # next iteration, forward whatever we just received
        sendBuf = recvBuf.clone()

    return result


def AllRecursiveDoubling(sendTensor, gpSize, rank):
    # Recursive Doubling AllGather:
    # Each step k, process i talks to process i XOR 2^k.
    # Step 0: exchange with neighbor 1 away  -> each has 2 chunks
    # Step 1: exchange with neighbor 2 away  -> each has 4 chunks
    # Step 2: exchange with neighbor 4 away  -> each has 8 chunks
    # ...and so on. Only takes log2(N) steps total.
    #
    # pros: low latency (log2(N) steps)
    # cons: requires gpSize to be a power of 2

    # Make sure it is a power of 2
    assert (gpSize & (gpSize - 1)) == 0, "gp size must be a power of 2 for recursive doubling"

    # chunkSize = number of elements in each process's input tensor
    # sendTensor is the chunk we start with, and it's always the same size regardless of how many chunks we have in result
    chunkSize = sendTensor.numel() 

    # result buffer to hold all chunks (gpSize total)
    result = torch.zeros(chunkSize * gpSize, dtype=sendTensor.dtype)

    # start with just our own chunk in the right spot in the result
    # rank*chunkSize : start of our chunk, (rank+1)*chunkSize : end of our chunk
    result[rank * chunkSize:(rank + 1) * chunkSize] = sendTensor.clone()

    # we double the number of chunks we have each step, so we only need log2(gpSize) steps to get everything
    numSteps = int(math.log2(gpSize))


    # each step, exchange with the process that is 2^k away (XOR gives us that partner)
    # after step k, we have 2^(k+1) chunks because we get everything our partner has, which is the same amount as we had before the exchange
    for step in range(numSteps):
        # partner is the process that has the next set of chunks we need, which is 2^step away from us
        partner = rank ^ (1 << step)

        # send the chunks we have so far to our partner, and receive their chunks
        mask = (1 << (step + 1)) - 1

        # the start of our contiguous group in the result buffer
        groupStart = (rank & ~mask)

        # how many chunks we currently hold (doubles each step)
        sendCount = (1 << step)

        # figure out which half of the current group we hold, so we know which chunks to send
        # if group is [0,1,2,3] and we hold [0,1], we send the first half (0,1). If we hold [2,3], we send the second half (2,3).
        if rank < partner:
            myStart = groupStart
        else:
            myStart = groupStart + sendCount

        # grab the chunks we hold and send them
        sendData = result[myStart * chunkSize:(myStart + sendCount) * chunkSize].clone()
        recvData = torch.zeros(sendCount * chunkSize, dtype=sendTensor.dtype)

        # swap with partner
        sendReq = dist.isend(sendData, dst=partner)
        recvReq = dist.irecv(recvData, src=partner)
        sendReq.wait()
        recvReq.wait()

        # figure out where to place the received chunks in result        
        # the partner's group starts at the same place as ours, but they hold the opposite half
        if rank < partner:
            recvStart = myStart + sendCount
        else:
            recvStart = groupStart

        result[recvStart * chunkSize:(recvStart + sendCount) * chunkSize] = recvData

    return result


def AllSwing(sendTensor, gpSize, rank):
    # Swing AllGather:
    # Similar idea to recursive doubling (log2(N) steps, exchange with XOR partner)
    # but the ORDER of which bit we XOR changes; we alternate between low and
    # high bits instead of just going 0,1,2,3,...
    # 
    # For N=8 (3 steps): bit order is [0, 2, 1] -> distances [1, 4, 2]
    # For N=4 (2 steps): bit order is [0, 1]    -> same as recursive doubling
    # For N=16 (4 steps): bit order is [0, 3, 1, 2] -> distances [1, 8, 2, 4]
    #
    # Because the bit order is shuffled, we can't assume contiguous chunks
    # anymore; we have to track which chunks each process holds
    # and exchange chunk indices along with the data.
    #
    # pros: also low latency (log2(N) steps), but can have better performance than recursive doubling for some network topologies because it doesn't always talk to the same partner each step
    # cons: gpSize MUST be a power of 2

    # make sure it is a power of 2
    assert (gpSize & (gpSize - 1)) == 0, "gp size must be a power of 2 for swing"

    # chunkSize = number of elements in each process's input tensor
    chunkSize = sendTensor.numel()

    # we need to do log2(gpSize) steps to get everything, and the bit we XOR for the partner is determined by the step number and the swing bit sequence
    numSteps = int(math.log2(gpSize))


    # result buffer to hold all chunks (gpSize total)
    result = torch.zeros(chunkSize * gpSize, dtype=sendTensor.dtype)
    # start with just our own chunk in the right spot in the result
    # rank*chunkSize : start of our chunk, (rank+1)*chunkSize : end of our chunk

    result[rank * chunkSize:(rank + 1) * chunkSize] = sendTensor.clone()

    # build the swing bit sequence by interleaving from both ends
    # for 3 steps: lo=0,hi=2 -> [0, 2, 1]

    swingBits = []
    lo, hi = 0, numSteps - 1
    while len(swingBits) < numSteps:
        if lo <= hi:
            swingBits.append(lo)   # take from the low end
            lo += 1
        if len(swingBits) < numSteps and lo <= hi:
            swingBits.append(hi)   # take from the high end
            hi -= 1

    # keep track of which chunk indices we currently hold
    # initially we only hold our own chunk, which is index "rank"
    # as we receive new chunks from our partners, we add those indices to this set so we know what to send in future steps
    held = set()
    held.add(rank)

    # each step, exchange with the process that is 2^bit away (XOR gives us that partner)
    # after step k, we have all the chunks from both ourselves and our partner, so we add those chunk indices to our held set
    for stepI in range(numSteps):
        bit = swingBits[stepI]
        distVal = 1 << bit         # actual XOR distance for this step
        partner = rank ^ distVal   # who we talk to

        # gather everything we currently have to send
        heldList = sorted(held)
        numToSend = len(heldList)

        # we have to send the indices of the chunks we hold along with the data, so our partner knows where to put them in their result buffer. We pack the indices into a tensor and concatenate the corresponding chunks into a send buffer.
        sendIndices = torch.tensor(heldList, dtype=torch.long)

        # the data we send is all the chunks we currently hold, concatenated together. We sort heldList to ensure a consistent order of chunks in the send buffer.
        sendData = torch.cat([result[i * chunkSize:(i + 1) * chunkSize] for i in heldList])

        # first tell partner how many chunks we're sending (they need to know
        # how big of a recv buffer to allocate)
        myCount = torch.tensor([numToSend], dtype=torch.long)

        # exchange counts so we know how many chunks partner is sending
        # we have to do this with separate sends/recvs before we exchange the actual data, because we need to know how big the recv buffer should be for the data exchange.
        partnerCountT = torch.tensor([0], dtype=torch.long)


        # exchange counts with partner
        sreq = dist.isend(myCount, dst=partner)
        rreq = dist.irecv(partnerCountT, src=partner)
        sreq.wait()
        rreq.wait()

        # now we know how many chunks partner is sending, so we can allocate the recv buffer for both the indices and the data before we exchange the actual chunk indices and data with partner.
        partnerCount = partnerCountT.item()

        # allocate recv buffers now that we know the size
        partnerIndices = torch.zeros(partnerCount, dtype=torch.long)
        recvData = torch.zeros(partnerCount * chunkSize, dtype=sendTensor.dtype)

        # exchange the chunk indices so we know where to place them
        sreq = dist.isend(sendIndices, dst=partner)
        rreq = dist.irecv(partnerIndices, src=partner)
        sreq.wait()
        rreq.wait()

        # exchange the actual chunk data
        sreq = dist.isend(sendData, dst=partner)
        rreq = dist.irecv(recvData, src=partner)
        sreq.wait()
        rreq.wait()

        # place each received chunk into the right slot in result
        for iPos, i in enumerate(partnerIndices.tolist()):
            if i not in held:
                # i is the original chunk index (0 to gpSize-1) that we just got from partner, and iPos is its position in the recvData buffer (0 to partnerCount-1)
                # we place that chunk into the right spot in result based on its original index i, which tells us where it belongs in the final allgather output. We also add it to our held set so we know we have it for future sends.
                result[i * chunkSize:(i + 1) * chunkSize] = \
                    recvData[iPos * chunkSize:(iPos + 1) * chunkSize]
                held.add(i)

    return result
