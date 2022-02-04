# Simpletuner
Tool for running Combined Elimination against custom projects.

## Quickstart
Simpletuner comes pre-prepared with two example projects to optimize:

 - A simple example project (invoked with `--context ExampleWorkerContext`)
 - The ChipsAlliance SweRV EH1 verilated core (`--context SweRVWorkerContext`)

### Running Simpletuner on native machine
Running Simpletuner is a two-step process:
1) Generate the flags file the Combined Elimination will use:
```
$ gen-flags.py --cc $(which gcc) > flag-sets/my-flag-set.flags
```
2) Run Simpletuner, optimising the example project for size using the above flags:
```
$ simpletuner.py --context ExampleWorkerContext --benchmark size --flags-file flag-sets/my-flag-set.flags --cc $(which gcc) -j $(nproc)
```
This will start a lengthy Combined Elimination run for the `ExampleWorkerContext` (with a very noisy log output) accross `nproc` threads for the native system compiler.

To view the live output, look into the `workspace/` directory (which should be created when running `simpletuner` for the first time), and look into the latest directory.
 
### SweRV
Running the ChipsAlliance SweRV EH1 core is a bit more involved. the `eh1/` directory contains a `Makefile` which does the following:
1) Fetch `verilator` source from GitHub
2) Builds `verilator` and installs into the same directory
3) Fetch the `SweRV` source from GitHub
4) Build the `SweRV` core from source
5) Package the whole directory into a `eh1.tar.gz`

You won't have to generate the flags file for this project - you can just use the `flag-sets/riscv.flags` flag set.

Make sure that you have a `riscv32-unknown-elf-gcc` compiler in your path, (you can download an upstream `riscv32` compiler from [here](https://www.embecosm.com/resources/tool-chain-downloads/#riscv-stable)), and invoke the `simpletuner` script as follows:
```commandline
SWERV_SOURCE_TAR=$(realpath eh1/eh1.tar.gz) -j 8 --context SweRVWorkerContext --benchmark execute --flags-file flag-sets/riscv.flags --cc [path to riscv32-unknown-elf-gcc]
```

## Creating custom worker contexts

A "Worker context" is simply a class within the `context/` that implements certain methods required by the Simpletuner driver.

Simpletuner comes pre-included with two worker contexts:
```commandline
context
├── ExampleWorkerContext.py
└── SweRVWorkerContext.py
```

The `ExampleWorkerContext.py` file provides a very simple worker context that shows how to implement the callbacks neccesary for Simpletuner to function.
