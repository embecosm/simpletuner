#!/usr/bin/env python3
import copy;
import logging;
import argparse;
import importlib;
from tempfile import TemporaryDirectory;

parser = argparse.ArgumentParser(description='Remove redundant compiler flags.');

parser.add_argument("--cc", default=None,
                    help="C compiler to use for initial flag validation.");

parser.add_argument("--context", default=None,
                    help="Specify which worker context class to use. This is a user-defined classname.");

parser.add_argument("--benchmark", default=None,
                    help="Specify which benchmark to run. This parameter is specific to whatever worker context you selected in the --context parameter.");

parser.add_argument("--target", required=True, type=float,
                    help="Benchmark result to target. minimize-flags.py won't remove flags that affect this number.");

parser.add_argument("--starting-cflags-file", default=None,
                    help="C flags to start with. These can help speed up combined elimination. If you're trying to minimize size, try '-Os'. If you're trying to maximise performance, try '-O3' or '-Ofast'.");

args = parser.parse_args();

def get_worker_context_class(worker_context_classname):
    ctx_module = importlib.import_module("{}.{}".format("context", worker_context_classname));
    ctx_class = getattr(ctx_module, worker_context_classname);
    WorkerContext = ctx_class;

    return WorkerContext;

def minimize(input_flags, target, worker):
    current_flags = copy.deepcopy(input_flags);
    compulsory_flags = [];

    while len(current_flags) > 0:
        compile_ok = worker.compile([] + compulsory_flags);
        result = worker.benchmark();

        benchmark_ok = compile_ok and (result == target);

        if benchmark_ok:
            break;

        idx_mid = len(current_flags) // 2;
        while not benchmark_ok:
            include = current_flags[:idx_mid];
            exclude = current_flags[idx_mid:];

            logging.debug("include: " + ", ".join(include));
            logging.debug("exclude: " + ", ".join(exclude));

            compile_ok = worker.compile(include + compulsory_flags);
            result = worker.benchmark();
            benchmark_ok = compile_ok and (result == target);

            if not benchmark_ok:
                if len(exclude) == 1:
                    compulsory_flag = exclude[0];

                    logging.debug("Found failing flag: " + compulsory_flag);
                    compulsory_flags.append(compulsory_flag);
                    del current_flags[idx_mid:];
                    break;

                logging.debug("Build failed");
                idx_mid = (idx_mid + len(current_flags)) // 2;

            else:
                logging.debug("Build success");
                del current_flags[idx_mid:];
                break;

    logging.info("We're done - compulsory flags: " + str(compulsory_flags));
    return compulsory_flags;

def main():
    logging.basicConfig(
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    )

    logging.root.setLevel(logging.NOTSET)
    logger = logging.getLogger()

    # The WorkerContext class that we will be using
    if args.context is None:
        logger.warning("No worker context specified, using ExampleWorkerContext")
        worker_context_classname = "ExampleWorkerContext"
    else:
        worker_context_classname = args.context

    WorkerContext = get_worker_context_class(worker_context_classname)

    if args.benchmark is None:
        logger.error("You must provide a benchmark to use via the --benchmark flag. Aborting.");
        logger.error("Valid --benchmark arguments: " + ", ".join(
            ['"' + benchmark + '"'
             for benchmark in WorkerContext.get_available_benchmark_types()]));
        exit(1);
    elif args.benchmark not in WorkerContext.get_available_benchmark_types():
        logger.error("--benchmark \"{}\" is invalid for worker context \"{}\""\
                     .format(args.benchmark, args.context));
        logger.error("Valid --benchmark arguments: " + ", ".join(
            ['"' + benchmark + '"'
             for benchmark in WorkerContext.get_available_benchmark_types()]));
        exit(1);
    else:
        logger.info("Will be using the benchmark \"{}\"".format(args.benchmark));

    workspace = TemporaryDirectory();
    logger.info("Using temporary workspace directory \"{}\"".format(workspace.name));

    worker = WorkerContext(0, workspace.name, args.cc, args.benchmark);
    worker.init_workspace();

    with open(args.starting_cflags_file, "r") as file:
        raw = file.read();
        starting_flags = [e.strip() for e in raw.split()]

    minimized_flags = minimize(starting_flags, args.target, worker);
    print("Reduced flags:");
    for flag in minimized_flags:
        print(flag);

    # for flag in ["-O0", "-O1", "-O2", "-O3", "-Ofast", "-Os"]:
    #     context.compile([flag]);
    #     result = context.benchmark();
    #     logger.info("Got result for {}: {}".format(flag, result));

    workspace.cleanup();


if __name__ == "__main__":
    main()
