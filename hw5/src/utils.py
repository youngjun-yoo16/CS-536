import os
import torch
import torch.distributed as dist
import time
from datetime import timedelta


def setup(rank, gpSize, backend="gloo"):
    # initialize the process group so all ranks can talk to each other.
    # MASTER_ADDR/PORT tell everyone where rank 0 is listening.
    os.environ["MASTER_ADDR"] = os.environ.get("MASTER_ADDR", "10.0.0.1")
    os.environ["MASTER_PORT"] = os.environ.get("MASTER_PORT", "25565")
    timeout = timedelta(minutes=30)
    dist.init_process_group(backend, rank=rank, world_size=gpSize, timeout=timeout)


def cleanup():
    # make sure all ranks are done before tearing down.
    dist.barrier()
    dist.destroy_process_group()


def getTensor(sizeBytes, rank, fillValue=None):
    # create a flat tensor.
    # by default fills with the rank number so we can verify correctness
    # (each rank's chunk should contain its own rank value.
    numElements = sizeBytes // 4  # float32 = 4 bytes each
    if numElements < 1:
        numElements = 1
    val = fillValue if fillValue is not None else float(rank)
    return torch.full((numElements,), val, dtype=torch.float32)


def benchmark(fn, warmup=2, repeats=5):
    # time a collective operation, returns the median time in seconds.
    # we do a few warmup rounds first so caches/JIT are primed,
    # then time `repeats` runs with barriers to sync all processes.

    for _ in range(warmup):
        fn()
    dist.barrier()

    times = []
    for _ in range(repeats):
        dist.barrier() # sync everyone up before starting the timer, so we only measure the fn() runtime                 
        start = time.perf_counter() # start timer after barrier to get clean timing of just
        fn() # run the actual code we want to benchmark
        dist.barrier() # make sure everyone finishes before we stop the timer           
        end = time.perf_counter() # stop timer after barrier to get clean timing of just fn() runtime
        times.append(end - start)

    times.sort()
    return times[len(times) // 2]

# This is for us to print the sizes in MB/KB 
def sizeToStr(sizeBytes):
    if sizeBytes < 1024:
        return f"{sizeBytes}B"
    elif sizeBytes < 1024 * 1024:
        return f"{sizeBytes // 1024}KB"
    else:
        return f"{sizeBytes // (1024 * 1024)}MB"
