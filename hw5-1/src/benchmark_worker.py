# Benchmark worker; this file gets launched once per rank by torchrun.
# Each rank runs the same code but with a different RANK env var.
# We test every algorithm at each message size, verify correctness,
# then time it and dump results to JSON.

import os
import sys
import json
import torch
import torch.distributed as dist

# make sure we can import the other modules in src/
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from utils import setup, cleanup, getTensor, benchmark
from allgather import AllRing, AllRecursiveDoubling, AllSwing
from broadcast import BcBinaryTree, BcBinomialTree


def verifyAll(result, gpSize, chunkSize):
    # after allgather, chunk i should be filled with float(i)
    # because getTensor fills with the rank number by default
    for r in range(gpSize):
        expected = float(r)
        segment = result[r * chunkSize:(r + 1) * chunkSize]
        if not torch.allclose(segment, torch.full_like(segment, expected)):
            return False
    return True


def verifyBroadcast(result, rootValue):
    # after broadcast, every element should equal rootValue
    return torch.allclose(result, torch.full_like(result, rootValue))


def runAllgatherBenchmark(rank, gpSize, messageSizes):
    # run all 3 allgather algorithms across every message size
    results = {}

    # algoName -> algoFn for allgather algorithms we want to test
    algorithms = {
        "ring": AllRing,
        "recursive_doubling": AllRecursiveDoubling,
        "swing": AllSwing,
    }

    # recursive_doubling and swing need power-of-2 gp size
    isPowerOf2 = (gpSize & (gpSize - 1)) == 0


    for algoName, algoFn in algorithms.items():
        if not isPowerOf2 and algoName in ("recursive_doubling", "swing"):
            if rank == 0:
                print(f"  Skipping {algoName}: gpSize={gpSize} is not a power of 2")
            continue

        # run the benchmark for this algorithm across all message sizes, store results in a dict
        results[algoName] = {}
        for msgSize in messageSizes:
            # float32 is 4 bytes, so divide to get element count
            # we use chunkSize in the verification function to know how big each rank's contribution should be in the final allgather output. We also use it to create the input tensor of the right size for this message size.
            chunkSize = max(msgSize // 4, 1)
            sendTensor = getTensor(msgSize, rank)

            # Run once and verify the output is correct
            dist.barrier()
            out = algoFn(sendTensor, gpSize, rank)
            correct = verifyAll(out, gpSize, chunkSize)
            if rank == 0 and not correct:
                print(f"  WARNING: {algoName} failed verification at msgSize={msgSize}")

            # Benchmark the algorithm, store elapsed time in results dict
            # we create the input tensor inside the run() function so that we include its creation time in the benchmark. This way we measure the full time it takes to do the allgather including preparing the data, which is more realistic. We also make sure to create a fresh tensor each time to avoid any caching effects that might make subsequent runs faster.
            def run():
                t = getTensor(msgSize, rank)
                algoFn(t, gpSize, rank)

            elapsed = benchmark(run, warmup=2, repeats=5)
            results[algoName][msgSize] = elapsed

            if rank == 0:
                from utils import sizeToStr
                print(f"  {algoName} msg={sizeToStr(msgSize)}: {elapsed*1000:.3f} ms (correct={correct})")

    return results


def runBcBench(rank, gpSize, messageSizes):
    # run both broadcast algorithms across every message size
    results = {}

    algorithms = {
        "binary_tree": BcBinaryTree,
        "binomial_tree": BcBinomialTree,
    }

    root = 0
    rootValue = 42.0  # the value that the root rank will fill its tensor with, and that we expect everyone to end up with after the broadcast, it can be any float value since we're just verifying that all elements match it. We choose 42.0 as a fun arbitrary value.


    # run the benchmark for this algorithm across all message sizes, store results in a dict
    for algoName, algoFn in algorithms.items():
        results[algoName] = {}
        for msgSize in messageSizes:
            # root fills tensor with rootValue, everyone else starts with zeros
            if rank == root:
                tensor = getTensor(msgSize, rank, fillValue=rootValue)
            else:
                tensor = torch.zeros(max(msgSize // 4, 1), dtype=torch.float32)

            # Run once and verify the output is correct
            dist.barrier()
            out = algoFn(tensor.clone(), gpSize, rank, root=root)
            correct = verifyBroadcast(out, rootValue)
            if rank == 0 and not correct:
                print(f"  WARNING: {algoName} failed verification at msgSize={msgSize}")

            # Benchmark the algorithm, store elapsed time in results dict
            def run():
                if rank == root:
                    t = getTensor(msgSize, rank, fillValue=rootValue)
                else:
                    t = torch.zeros(max(msgSize // 4, 1), dtype=torch.float32)
                algoFn(t, gpSize, rank, root=root)

            elapsed = benchmark(run, warmup=2, repeats=5)
            results[algoName][msgSize] = elapsed

            if rank == 0:
                from utils import sizeToStr
                print(f"  {algoName} msg={sizeToStr(msgSize)}: {elapsed*1000:.3f} ms (correct={correct})")

    return results


def main():
    # torchrun sets RANK and gpSize for us
    rank = int(os.environ["RANK"])
    gpSize = int(os.environ["WORLD_SIZE"])

    # set up the process group so we can use dist.send/recv etc.
    setup(rank, gpSize)

    print(f"[rank {rank}] Joined process group (gpSize={gpSize})")
    if rank == 0:
        print(f"=== Running benchmarks with gpSize={gpSize} ===")

    # first arg: what to benchmark (all / allgather / broadcast)
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    # second arg: where to save JSON results (only rank 0 writes)
    outputFile = sys.argv[2] if len(sys.argv) > 2 else None

    # message sizes can be overridden via env var 
    messageSizesStr = os.environ.get("MESSAGE_SIZES", "")
    if messageSizesStr:
        messageSizes = [int(x) for x in messageSizesStr.split(",")]
    else:
        messageSizes = [
            1024,           # 1 KB
            4096,           # 4 KB
            16384,          # 16 KB
            65536,          # 64 KB
            262144,         # 256 KB
            1048576,        # 1 MB
            4194304,        # 4 MB
            16777216,       # 16 MB
            67108864,       # 64 MB
        ]

    allResults = {"gp_size": gpSize, "message_sizes": messageSizes}

    if mode in ("all", "allgather"):
        if rank == 0:
            print("\n--- AllGather Benchmarks ---")
        print(f"[rank {rank}] Starting allgather benchmarks...")
        allResults["allgather"] = runAllgatherBenchmark(rank, gpSize, messageSizes)
        print(f"[rank {rank}] Finished allgather benchmarks.")

    if mode in ("all", "broadcast"):
        if rank == 0:
            print("\n--- Broadcast Benchmarks ---")
        print(f"[rank {rank}] Starting broadcast benchmarks...")
        allResults["broadcast"] = runBcBench(rank, gpSize, messageSizes)
        print(f"[rank {rank}] Finished broadcast benchmarks.")

    # only rank 0 writes results to disk
    if rank == 0 and outputFile:
        with open(outputFile, "w") as f:
            jsonResults = {}
            for key, val in allResults.items():
                if isinstance(val, dict):
                    jsonResults[key] = {}
                    for algo, sizes in val.items():
                        if isinstance(sizes, dict):
                            jsonResults[key][algo] = {str(k): v for k, v in sizes.items()}
                        else:
                            jsonResults[key][algo] = sizes
                else:
                    jsonResults[key] = val
            json.dump(jsonResults, f, indent=2)
            print(f"\nResults saved to {outputFile}")

    print(f"[rank {rank}] All done, cleaning up...")
    cleanup()
    print(f"[rank {rank}] Exiting.")


if __name__ == "__main__":
    main()
