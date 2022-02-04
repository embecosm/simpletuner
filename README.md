# Simpletuner
Tool for running Combined Elimination against custom projects.

## Quickstart
Simpletuner comes pre-prepared with two example projects to optimize:

 - A simple example project (invoked with `--context ExampleWorkerContext`)
 - The ChipsAlliance SweRV EH1 verilated core (`--context SweRVWorkerContext`)

### Running simpletuner on native machine
Running Simpletuner is a two-step process:
1) Generate the flags file the Combined Elimination will use:
```
$ gen-flags.py --cc $(which gcc) > flag-sets/my-flag-set.flags
```
2) Run Simpletuner, optimising the example project for size using the above flags:
```
$ simpletuner.py --context ExampleWorkerContext --benchmark size --flags-file flag-sets/my-flag-set.flags --cc $(which gcc) -j $(nproc)
```
This will start a lengthy Combined Elimination run (with a very noisy log output) accross `nproc` threads for the native system compiler.

To view the live output, look into the `workspace/` directory (which should be created when running `simpletuner` for the first time), and look into the latest directory.

 
### SweRV

### Simpletuner

## Quickstart
