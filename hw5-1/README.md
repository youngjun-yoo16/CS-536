# HW5 — Collective Communication Algorithms

This project implements and benchmarks several collective communication algorithms used in distributed computing. The two collectives we focus on are **AllGather** and **Broadcast**, and we implement multiple algorithms for each one so we can compare how they perform at different message sizes and process counts.

Everything runs inside Docker containers using PyTorch's distributed communication backend (gloo). Each "rank" is a separate process, and they communicate using `torch.distributed` send/recv calls.

## Project Structure

```
hw5/
├── Dockerfile                    # container setup with Python 3.11 + PyTorch 
├── requirements.txt              # torch, matplotlib, numpy
├── src/
│   ├── allgather.py              # 3 AllGather implementations (Ring, Recursive Doubling, Swing)
│   ├── broadcast.py              # 2 Broadcast implementations (Binary Tree, Binomial Tree)
│   ├── benchmark_worker.py       # main entry point torchrun launches one per rank
│   ├── plot_results.py           # reads the JSON output and makes comparison plots
│   └── utils.py                  # process group setup/teardown, tensor creation, timing helpers
├── scripts/
│   ├── setup.sh                  # installs Docker, Python, PyTorch, and everything else
│   ├── runBench.sh               # full benchmark suite (builds image, sweeps ranks + msg sizes)
│   ├── runQuick.sh               # quick 2-rank smoke test to check correctness
│   ├── bonusSetupRing.sh         # sets up ring network topology on machines/VMs
│   ├── bonusVerifyRing.sh        # verifies ring routing with ping/traceroute
│   ├── bonusSetupSsh.sh          # passwordless SSH setup between machines
│   └── bonusRunDist.sh           # runs benchmark across machines in the ring
├── results/                      # JSON benchmark data (generated after running)
└── plots/                        # PNG comparison charts (generated after running)
```

### Setup

Install everything (Docker, Python, PyTorch, networking tools):

```bash
sudo ./scripts/setup.sh
```

### Quick Test (just check correctness)

This builds the Docker image and runs a quick 2-rank test with small message sizes (1KB, 4KB, 16KB). Good for making sure nothing is broken before running the full everything.

```bash
./scripts/runQuick.sh
```

You should see something like:
```
=== Running benchmarks with gpSize=2 ===

--- AllGather Benchmarks ---
  ring msg=1KB: 0.823 ms (correct=True)
  recursive_doubling msg=1KB: 0.691 ms (correct=True)
  swing msg=1KB: 0.705 ms (correct=True)
  ...

--- Broadcast Benchmarks ---
  binary_tree msg=1KB: 0.412 ms (correct=True)
  binomial_tree msg=1KB: 0.389 ms (correct=True)
  ...
```

The `correct=True` part is key; it means the output matched what we expected (each rank ended up with the right data after the collective).

### Full Benchmark Suite

This runs all algorithms at 2, 4, and 8 ranks, sweeping over message sizes from 1KB up to 16MB. It also generates plots at the end.

```bash
./scripts/runBench.sh
```

- JSON timing data in `results/` (one file per rank count)
- PNG plots in `plots/` (4 plots total)

### Customizing the Benchmark

You can also control what gets run with environment variables:

```bash
# only test with 2 and 4 ranks, skip 8
RANKS="2 4" ./scripts/runBench.sh

# only benchmark allgather (skip broadcast)
MODE=allgather ./scripts/runBench.sh

# cap message size at 4MB instead of 16MB (faster)
MAX_MSG=4194304 ./scripts/runBench.sh

# specify exact message sizes to test
MSG_SIZES="1024,65536,1048576" ./scripts/runBench.sh

# combine them
RANKS="2 4" MODE=allgather MAX_MSG=4194304 ./scripts/runBench.sh
```

## Algorithms

### AllGather

In AllGather, every process starts with one chunk of data. After the operation finishes, every process has ALL chunks from every other process; so if there's N processes, the result is N times bigger than the input.

We implement three different algorithms:

#### Ring

All the processes in a ring: each step, every process sends what it has to its right neighbor and receives from its left neighbor. After N-1 steps the data has traveled all the way around and everyone has everything.

- **Steps**: N - 1 (where N = number of processes)
- **Good for**: Large messages, since each step only sends one chunk so the bandwidth usage is spread out evenly
- **Bad for**: Small messages, since many steps means a lot of latency overhead per step adds up

#### Recursive Doubling

Each step, process `i` exchanges data with process `i XOR 2^k` (where k is the step number, starting from 0). So step 0 you talk to someone 1 away, step 1 you talk to someone 2 away, step 2 someone 4 away, etc. Every step, the amount of data each process holds doubles because you get everything your partner has.

- **Steps**: log₂(N)
- **Good for**: Fewer steps means less latency, so better for small messages
- **Bad for**: Each step sends more and more data (doubles), so bandwidth isn't used as efficiently as ring for very large messages

#### Swing

Same number of steps as recursive doubling (log₂(N)), but instead of going through the XOR bits in order (0, 1, 2, ...) it alternates between low bits and high bits. For example with 8 processes (3 steps), the bit sequence is [0, 2, 1] instead of [0, 1, 2], so the communication distances are [1, 4, 2] instead of [1, 2, 4].

Because the bit order is shuffled, we can't assume the chunks are contiguous anymore, so the implementation has to track which chunk indices each process holds and send those indices along with the data so the receiving side knows where to put everything.

- **Steps**: log₂(N)
- **Good for**: Can be better than recursive doubling on some network topologies because it doesn't always talk to the same pattern of partners

### Broadcast

In Broadcast, one process (the root, usually rank 0) has data, and after the operation every process has a copy of that data.

We implement two algorithms:

#### Binary Tree

Lay out all processes in a binary tree (node i's children are 2i+1 and 2i+2). The root sends to its two children, they each send to their two children, and so on. Each node does at most 1 receive and 2 sends.

- **Steps**: ⌈log₂(N)⌉
- **Downside**: In the first step only 1 process is sending (the root), so only 2 links are active. Subsequent steps use more links, but the startup is slow.

#### Binomial Tree

Works in ⌈log₂(N)⌉ steps going from the biggest power-of-2 distance down to 1. In each step, every process that already has the data and is "aligned" to the right power of 2 sends to a partner. This means more sends can happen in parallel compared to the binary tree.

For example with 4 processes:
- Step 1: rank 0 sends to rank 2 (distance 2)
- Step 0: rank 0 sends to rank 1, AND rank 2 sends to rank 3 (distance 1, both in parallel)

So in step 0 two sends happen at the same time, which is better than binary tree where only the root is active initially.

- **Steps**: ⌈log₂(N)⌉
- **Better than binary tree**: More parallelism, especially in the later steps

## How the Benchmarking Works

The `benchmark_worker.py` file is the main entry point. `torchrun` launches N copies of it (one per rank), each getting a different `RANK` environment variable. Each rank:

1. Initializes the process group (so all ranks can talk to each other via `torch.distributed`)
2. For each algorithm and each message size:
   - Creates a tensor filled with its rank number (so rank 0 fills with 0.0, rank 1 fills with 1.0, etc.)
   - Runs the algorithm once and **verifies correctness**; for AllGather we check that chunk i contains float(i), for Broadcast we check everyone got the root's value
3. Rank 0 writes all the timing results to a JSON file

The timing uses barriers before and after to make sure all processes start and finish together, so we're measuring the actual collective time and not just one rank's view of it.

## Output

### Results (JSON)

One file per process count in `results/`:

Each file has timing data keyed by algorithm name and message size (in bytes). Times are in seconds.

### Plots (PNG)

Four plots get generated in `plots/`.

## Bonus: Ring Topology

For the bonus part, we set up an actual ring network topology using Ubuntu ARM VMs with bridged networking, all connected through a 5-port switch. Instead of all machines being able to talk directly to each other, we force traffic to go around a ring; Machine 0 can only send directly to Machine 1, Machine 1 to Machine 2, etc., and Machine 4 wraps back to Machine 0.

This means the Ring AllGather algorithm actually runs on a physical ring, which is kind of the whole point of that algorithm.

### Prerequisites (Before Meeting Up)

Each group member needs to do this on their own machine:

1. **Set up an Ubuntu ARM VM** with the network adapter set to **bridged mode** (so the VM gets its own MAC address on the physical LAN through your laptop's ethernet port)
2. **Install dependencies inside the VM:**
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip net-tools traceroute openssh-server iproute2
   pip3 install torch --index-url https://download.pytorch.org/whl/cpu
   pip3 install matplotlib numpy
   ```
3. **Make sure SSH is running:** `sudo systemctl enable --now ssh`
4. **Clone/copy the hw5 project** to the same path on every VM (e.g. `~/hw5`)
5. **Find your bridged interface name:** run `ip link show`;

### Step-by-Step Setup (When Everyone Is Plugged Into the Switch)

**Step 1 — Assign machine numbers.** Each person picks a number 0 through 4. This determines your IP and your position in the ring.

**Step 2 — Everyone runs the ring setup script** (each person on their own VM):
```bash
sudo ./scripts/bonusSetupRing.sh <YOUR_NUMBER> 5 <INTERFACE>
```

Everyone should run this around the same time; the script tries to ping your right neighbor to learn their MAC address, and retries up to 10 times if they're not ready yet.

**Step 3 — Verify the ring is working** (everyone can run this):
```bash
sudo ./scripts/bonusVerifyRing.sh <YOUR_NUMBER> 5 <INTERFACE>
```
Check that:
- All 4 other machines show `OK` on ping
- Traceroute hop counts increase going around the ring (1 hop to your right neighbor, 2 hops to the next one)

**Step 4 — Set up passwordless SSH** (everyone runs this):
```bash
SSH_USER=<your_vm_username> ./scripts/bonusSetupSsh.sh <YOUR_NUMBER> 5
```
You'll type each machine's password once. After that SSH works without passwords.

**Step 5 — Run the benchmark from Machine 0:**
```bash
SSH_USER=<vm_username> ./scripts/bonusRunDist.sh 5 all <INTERFACE>
```
This SSHs into each machine, launches one worker per machine, and collects results. Output goes to `results/` and `plots/` just like the Docker benchmarks.

### How the Ring Enforcement Works

Each machine's routing table only has a **direct route to itself and its right neighbor**. For every other machine, the route says "send it to my right neighbor and let them deal with it." So a packet from Machine 0 to Machine 3 goes:

```
Machine 0 → switch → Machine 1 (forwards) → switch → Machine 2 (forwards) → switch → Machine 3
```

- **Static IP** — `10.0.0.1` for Machine 0, `10.0.0.2` for Machine 1, etc.

