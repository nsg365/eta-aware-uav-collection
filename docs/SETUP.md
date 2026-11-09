# Setup

## Requirements

| Tool | Minimum | Why | Verified with |
|---|---|---|---|
| OS | Linux, macOS, or **Windows via WSL2 (Ubuntu 24.04)** | ns-3 is a Linux/macOS C++ toolchain project | macOS 26 (Darwin 25.5) |
| C++ compiler | g++ 11.1+ or clang++ 17+ (ns-3.47 builds as C++23) | ns-3.47 release notes | Apple clang 21 |
| CMake | 3.20+ | ns-3.47 | 4.4.2 |
| Python | **3.11+** (3.12 recommended) | our code uses `tomllib` (3.11+); pinned packages need 3.11+ | 3.14.0 |
| ns-3 | **exactly 3.47** | the simulation uses 3.47 APIs | 3.47 |
| Python packages | exact pins in `requirements.txt` | same results on every machine | see file |

Folder layout the scripts expect by default:

```
mlown/                      (any name)
├── ns3-workspace/ns-3.47/  ns-3 source + build
└── wsn-uav/                this repository
```

If ns-3 is somewhere else, set `export NS3_DIR=/path/to/ns-3.47` (add it to `~/.bashrc`).

---

## Windows: WSL2 + Ubuntu 24.04 (recommended for the team)

Work entirely **inside Ubuntu** (WSL), not in a Windows folder. Building ns-3 under `/mnt/c/...`
is many times slower and symlinks can break there.

### 1. Install WSL with Ubuntu 24.04 (once)

In **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Reboot if asked, then open **Ubuntu 24.04** from the Start menu and create a Linux user.
(If WSL is already installed with an older Ubuntu, check with `wsl -l -v`; Ubuntu 22.04 ships
Python 3.10, which is too old for this project.)

### 2. Install build tools (inside Ubuntu)

```bash
sudo apt update
sudo apt install -y build-essential cmake ninja-build git wget bzip2 \
                    python3 python3-venv python3-pip
g++ --version      # expect 13.x on Ubuntu 24.04 (needs >= 11.1)
cmake --version    # expect 3.28+ (needs >= 3.20)
python3 --version  # expect 3.12.x (needs >= 3.11)
```

### 3. Download and build ns-3.47

```bash
mkdir -p ~/mlown/ns3-workspace && cd ~/mlown/ns3-workspace
wget https://www.nsnam.org/releases/ns-3.47.tar.bz2
sha256sum ns-3.47.tar.bz2
# expect 8b3adca956c834ea436b915986ab8fd053e90041acae7426895d595aaa3ccc39
tar xjf ns-3.47.tar.bz2
cd ns-3.47
./ns3 configure --enable-modules="wifi;energy;internet;mobility"
```

Building only these four modules (plus their dependencies, chosen automatically) is much faster
than a full ns-3 build and is all this project needs. The build itself happens in step 4.

### 4. Get the project, link it into ns-3, build it

```bash
cd ~/mlown
git clone <your-team-repo-url> wsn-uav
cd wsn-uav
scripts/link_ns3.sh                          # links ns-3.47/scratch/wsn-uav and wsn-uav-range -> this repo
(cd ../ns3-workspace/ns-3.47 && ./ns3 build wsn-uav wsn-uav-range)
```

The first build compiles the ns-3 modules and is the slow step: measured 3 min on a 10-core Mac; expect roughly 10–30 min on a 4–8-core laptop under WSL (estimate, not measured).
Later builds only recompile what changed. If the build is killed or the laptop freezes,
WSL ran out of memory: use fewer parallel jobs, e.g. `./ns3 build -j 2 wsn-uav`.

### 5. Python environment

Ubuntu 24.04 does not allow `pip install` into the system Python, so use a virtual environment:

```bash
cd ~/mlown/wsn-uav
python3 -m venv .venv
source .venv/bin/activate          # run this in every new terminal before working
pip install -r requirements.txt
```

### 6. Check everything works

```bash
python3 -m pytest                  # expect: 26 passed
python3 -m experiments.run_experiment configs/example_wake_modes.toml
python3 -m analysis.aggregate results/wake_modes/runs.csv
```

If the simulation tests say *skipped*, the ns-3 program was not found: re-run step 4, or set
`NS3_DIR`.

### Editing with VS Code on Windows

Install the **WSL** extension in VS Code. Then, in the Ubuntu terminal, `cd ~/mlown/wsn-uav &&
code .` opens the project with VS Code running against the Linux files and toolchain. Your
Windows files are visible from Ubuntu under `/mnt/c/`, and the Ubuntu files from Windows
Explorer under `\\wsl$\Ubuntu-24.04\home\<user>\`.

### Common problems

| Symptom | Fix |
|---|---|
| `/usr/bin/env: 'bash\r': No such file or directory` | The repo was cloned on the Windows side with CRLF line endings. Clone inside Ubuntu instead (`.gitattributes` forces LF for new clones). |
| `error: externally-managed-environment` from pip | Activate the venv first (step 5). |
| `ModuleNotFoundError: tomllib` | Python is older than 3.11; use Ubuntu 24.04. |
| Build killed / very slow | Use `./ns3 build -j 2 wsn-uav`; make sure the files are under `~/`, not `/mnt/c/`. |
| `Target to build does not exist: wsn-uav` | Run `scripts/link_ns3.sh` (step 4), then `./ns3 configure ...` again. |

---

## macOS / Linux

Same steps as 3–6 above. On macOS, install the tools with Homebrew
(`brew install cmake ninja python@3.12`) and Xcode command-line tools (`xcode-select --install`);
on Linux, use your package manager as in step 2.
