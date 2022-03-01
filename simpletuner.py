#!/usr/bin/env python3
import os, sys, re, time, random, subprocess, shutil, string, json;
from datetime import datetime;
import copy;
import random;
import logging;
import multiprocessing as mp;
import argparse;
import importlib;

from flag import Flag;
from gcc import GCCDriver;

# See: https://stackoverflow.com/a/13941865 - we need this to catch
# `queue.Empty` exceptions
import queue; # Called "Queue" in Python 2

parser = argparse.ArgumentParser(description='Run combined elimination in parallel.');

def greater_than_one(value):
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError(
            "{} must be an integer greater than 1".format(value));
    return ivalue


parser.add_argument("-j", "--processes", type=greater_than_one,
                    default=None, # Will use mp.cpu_count();
                    help="Number of processes to spawn");

parser.add_argument("--context", default=None,
                    help="Specify which worker context class to use. This is a user-defined classname.");

parser.add_argument("--benchmark", default=None,
                    help="Specify which benchmark to run. This parameter is specific to whatever worker context you selected in the --context parameter.");

parser.add_argument("--config", default=None, dest="path_config",
                    help="Specify a config file that contains the flags to run Combined Elimination against.");

parser.add_argument("--cc", default=None, dest="path_cc",
                    help="C compiler to use for initial flag validation.");

parser.add_argument("--setup-workspace-only", action="store_true",
                    help="Exit after setting up a workspace for each"
                    " worker thread. Useful for when debugging your"
                    " worker context's `init_workspace` procedure.");

parser.add_argument("--drop-pessimizing-flags", action="store_true");

args = parser.parse_args();

workspace_file_all = None;
workspace_file_stdout = None;
workspace_file_stderr = None;

def check_cc_flags_worker(work_queue, result_queue):
    while True:
        work = work_queue.get(block=True);
        if work is None:
            return;

        flag, flag_idx, state, driver = work;
        ok = driver.check_flag(flag.values[flag.state]);

        result_queue.put((flag, flag_idx, state, ok), block=False);

def check_cc_flags(driver, config):
    work_queue = mp.Queue();
    result_queue = mp.Queue();
    n_workers = mp.cpu_count();

    workers = [mp.Process(name="check_cc_flags_worker#" + str(i),
                          target=check_cc_flags_worker,
                          args=(work_queue, result_queue))
               for i in range(n_workers)];

    for worker in workers:
        worker.daemon = True;
        worker.start();

    for flag_idx, flag in enumerate(config.flags):
        for state in flag.all_states():
            work_queue.put((flag, flag_idx, state, driver), block=False);

    for _ in range(n_workers):
        work_queue.put(None, block=False);

    for _ in config.flags:
        flag, flag_idx, state, ok = result_queue.get(block=True);

        if not ok:
            config.flags[flag_idx].exclusions = config.flags[flag_idx].exclusions.union({state});

    return config;

def worker_func(worker_ctx, work_queue, result_queue, binary_checksum_result_cache):
    idx = worker_ctx.idx;
    logger = logging.getLogger("Worker#{}".format(idx));

    logger.debug("Started");
    
    while True:
        job = work_queue.get(block=True);

        if job is None:
            logger.debug("Exiting");
            return;

        flags, state_variation = job;
        flags_str = " ".join(flags)

        if state_variation is None:
            logger.debug("Got job with state variation (<None>), flags \"{}\""\
                  .format(flags_str));
        else:
            logger.debug("Got job with state variation ({}, {}), flags \"{}\""\
                  .format(state_variation[0], state_variation[1], flags_str));

        compile_result = worker_ctx.compile(flags);
        if compile_result.ok:
            logger.debug("Successfully compiled with flags \"{}\"".format(flags_str));
            checksum = compile_result.checksum;

        else:
            logger.warning("Failed to compile with flags \"{}\"".format(flags_str));
            # Can't benchmark what we can't build: return.
            result_queue.put((flags, state_variation, None), block=False);
            continue;

        if checksum in binary_checksum_result_cache:
            score = binary_checksum_result_cache[checksum];
            logger.debug("Hit cache result \"{}\"! Re-using result {}"\
                         .format(checksum, score));

            result = (flags, state_variation, score);
            result_queue.put(result, block=False);
            continue;

        score = worker_ctx.benchmark();
        if score is not None:
            logger.debug("Successful benchmark, got score {} with flags \"{}\""\
                         .format(str(score), flags_str));
            binary_checksum_result_cache[checksum] = score;

        else:
            logger.warning("Failed to benchmark with flags \"{}\"".format(flags_str));

        result = (flags, state_variation, score);
        result_queue.put(result, block=False);

def create_cmd_from_flaglist(config):
    return [config.base_opt] + [str(flag) for flag in config.flags if flag.state != 0];

class Config:
    def __init__(self, base_opt, flags):
        self.base_opt = base_opt;
        self.flags = flags;

    class JSONDecoder(json.JSONDecoder):
        def __init__(self, *args, **kwargs):
            json.JSONDecoder.__init__(self, object_hook=self.object_hook, *args, **kwargs)

        def object_hook(self, dct):
            if "base_opt" in dct:
                base_opt = dct["base_opt"];

                flags = [];
                for dct_flag in dct["flags"]:
                    flag = Flag(dct_flag["name"], dct_flag["flags"]);
                    flag.state = dct_flag["state"];
                    flag.n_states = dct_flag["n_states"];
                    flag.exclusions = set(dct_flag["exclusions"]);
                    flags.append(flag);

                config = Config(base_opt, flags);
                return config;

            else:
                return dct;

    class JSONEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Config):
                return {
                    "base_opt": obj.base_opt,
                    "flags": [
                        {
                            'name': flag.name,
                            'flags': flag.values,
                            'state': flag.state,
                            'n_states': flag.n_states,
                            'exclusions': list(flag.exclusions)
                        } for flag in obj.flags
                    ]
                };

            # Let the base class default method raise the TypeError
            return json.JSONEncoder.default(self, obj)

def load_config_from_filename(filename):
    with open(filename, "r") as file:
        return json.loads(file.read(), cls=Config.JSONDecoder);

def create_run_directory(simpletuner_directory):
    random_suffix = "".join(
        [random.choice(string.ascii_letters + "0123456789") for _ in range(4)]);

    run_directory \
        = os.path.join(
            simpletuner_directory,
            datetime.now().strftime("%Y%m%d-%H%M%S-" + random_suffix));

    if os.path.isdir(run_directory):
        logging.error("You're either seriously unlucky, or something is "
                      "seriously amiss: Run directory \"{}\" already exists" \
                      .format(run_directory));
        sys.exit(1);

    os.mkdir(run_directory);
    return run_directory;

def create_workspace_directory():
    simpletuner_directory = os.path.join(os.getcwd(), 'workspace');

    if os.path.isdir(simpletuner_directory):
        logging.info("Reusing simpletuner directory \"{}\""\
                     .format(simpletuner_directory));
    else:
        try:
            os.mkdir(simpletuner_directory);
        except:
            logging.error("Failed to create top-level simpletuner directory \"{}\""\
                          .format(simpletuner_directory));
            sys.exit(1);

    return simpletuner_directory;

def work():
    global args;

    # Logging initialization code taken from here:
    # https://stackoverflow.com/a/56144390
    # Logging format handling and file/stream handling from here:
    # https://stackoverflow.com/a/46098711
    logging.basicConfig(
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    );

    # Create the main './workspace/' directory, if it doesn't exist already.
    simpletuner_directory = create_workspace_directory();

    # Create a unique run directory
    run_directory = create_run_directory(simpletuner_directory);

    # Create logging formatter separately, to then apply to each stream handler as they're created:
    # https://stackoverflow.com/a/11582124
    formatter: logging.Formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s: %(message)s')

    # Log output to file
    fh = logging.FileHandler(os.path.join(run_directory, "log.txt"));
    fh.setFormatter(formatter);
    logging.getLogger().addHandler(fh);

    # Set the priority to NOTSET (i.e. report everything.)
    logging.root.setLevel(logging.NOTSET);
    logger = logging.getLogger("SimpleTuner-Driver")

    if args.path_config is None:
        logger.error("You must provide a config file to use for combined elimination. Please generate one, or use a pre-generated one from the config/ directory. Aborting.");
        exit(1);

    if args.path_cc is not None:
        logger.info("Will be using the C compiler at \"{}\" to check flags.".format(args.path_cc));
    else:
        logger.error("You must provide a path to a C compiler. Aborting.");
        exit(1);

    # The WorkerContext class that we will be using
    if args.context is None:
        logger.warning("No worker context specified, using ExampleWorkerContext");
        worker_context_classname = "ExampleWorkerContext";
    else:
        worker_context_classname = args.context;

    ctx_module = importlib.import_module("{}.{}".format("context", worker_context_classname));
    ctx_class = getattr(ctx_module, worker_context_classname);
    WorkerContext = ctx_class;

    if WorkerContext is None:
        logger.error("Unknown WorkerContext classname: \"{}\"".\
                     format(worker_context_classname));
        sys.exit(1);
    else:
        logger.info("Will be using the WorkerContext class \"{}\"".format(worker_context_classname));

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

    n_tests = 0;

    if args.processes is not None:
        n_core_count = args.processes;
    else:
        n_core_count = mp.cpu_count();

    logger.info("Running with {} processes".format(n_core_count));

    # Global leaderboard to record _all_ results
    global_leaderboard = [];

    # "active" leaderboard, which only records flags whose score was an
    # improvement on their parent flag's score.
    leaderboard = [];

    # The current best result on the leaderboard
    best_flagpath = None;

    ### Phase 1: Flag discovery
    # Before we go and run the "real" search routine, first we find
    # out what each flag does individually, what impact it has, and if
    # it works at all.
    flags = [];

    config = load_config_from_filename(args.path_config);

    # Trim flags (useful for debug)
    # all_cc_flags = all_cc_flags[-20:-1];

    driver = GCCDriver(args.path_cc);

    config = check_cc_flags(driver, config);

    # Now, all_cc_flags may have excluded flags (because they
    # miscompiled.) It is not impossible that some flags had every
    # state excluded, and such flags we should simply remove from
    # consideration.
    config.flags = list(filter(
        lambda cc_flag: cc_flag.n_states > len(cc_flag.exclusions),
        config.flags)
    );

    # Calculate how many flag values we had in the beginning, and how many we have now.
    len_all_cc_flags_before = sum([flag.n_states for flag in config.flags]);
    len_all_cc_flags_after = sum([flag.n_states - len(flag.exclusions) for flag in config.flags]);

    logger.info("flags before excluding broken flags: {} entries.".format(len_all_cc_flags_before));
    logger.info("flags after excluding broken flags: {} entries.".format(len_all_cc_flags_after));

    # Fixup the flag initial state. We want to pick state 0 as much as
    # possible, but if that became an excluded state after being tested, then we need to update it.
    for flag in config.flags:
        flag.state = flag.valid_states()[0];

    # flags = config.flags;

    if len(config.flags) == 0:
        logger.error("After testing \"{}\" flags for function, we're left with 0"
                     " working flags! Maybe you're missing the C compiler or something?");
        sys.exit(1);

    # Create log files
    # global workspace_file_all;
    # workspace_file_all = open(os.path.join(run_directory, "all.log"), "w");
    #
    # global workspace_file_stdout;
    # workspace_file_stdout = open(os.path.join(run_directory, "stdout.log"), "w");
    # print("workspace_file_stdout: {}".format(workspace_file_stdout));
    #
    # global workspace_file_stderr;
    # workspace_file_stderr = open(os.path.join(run_directory, "stderr.log"), "w");
    # print("workspace_file_stderr: {}".format(workspace_file_stderr));

    # Create worker directories, and then the workers themselves.
    worker_ctxs = [];
    for idx in range(n_core_count):
        worker_workspace = os.path.join(run_directory, str(idx));

        os.mkdir(worker_workspace);
        worker_ctxs.append(WorkerContext(idx, worker_workspace, args.path_cc, args.benchmark));

    # Create shared dictionary mapping checksums to run times. This
    # avoids having to run binaries for which the result didn't
    # change.
    manager = mp.Manager();
    binary_checksum_result_cache = manager.dict();

    work_queue = mp.Queue();
    result_queue = mp.Queue();

    logger.debug("Creating {} worker processes".format(n_core_count));
    workers = [mp.Process(target=worker_func,
                          args=(worker_ctx, work_queue, result_queue, binary_checksum_result_cache))
               for worker_ctx in worker_ctxs];
    logger.debug("Done creating {} worker processes".format(n_core_count));

    logger.debug("Initializing {} worker contexts".format(n_core_count));

    init_workspaces_ok = [];
    for worker_ctx in worker_ctxs:
        init_workspaces_ok.append(worker_ctx.init_workspace());

    if any([not ok for ok in init_workspaces_ok]):
        logger.error("Atleast one workspace failed to initialize its workspace directory, aborting");
        sys.exit(1);

    logger.debug("Done initializing {} worker contexts".format(n_core_count));

    # If the user called us with "--setup-workspace-only", we are
    # done.
    if args.setup_workspace_only:
        sys.exit(0);

    for idx, worker in enumerate(workers):
        logger.debug("Starting Worker #{}".format(idx));
        worker.start();

    logger.debug("Started {} workers".format(n_core_count));

    f_live_global_leaderboard = open(
        os.path.join(run_directory, "global_leaderboard.live"), "w");

    n_iterations = 0;

    ### Enter main loop:
    while True:
        logger.info("Running iteration {}".format(n_iterations));

        # First, get the baseline for the current flag configuration
        work_queue.put((create_cmd_from_flaglist(config), None), block=False);
        result = result_queue.get(block=True);

        _, _, score = result;

        if score is None:
            logger.fatal("Failed to get baseline: This is unrecoverable. It may be the case that there's one or two flags causing the failure.");
            sys.exit(1);

        baseline_config = config;
        baseline = score;

        # Instantiate all the jobs we're working on
        state_variation_and_scores = [];
        n_jobs = 0;

        for flag_idx, flag in enumerate(config.flags):
            for other_state in flag.other_states():
                state_variation = (flag_idx, other_state)
                state_variation_and_scores.append((state_variation, None));

                state_variation_config = copy.deepcopy(config);
                state_variation_config.flags[flag_idx].state = other_state;

                work_queue.put((create_cmd_from_flaglist(state_variation_config),
                                state_variation),
                               block=False);
                n_jobs += 1;

        # It may be the case that we've reached the end of
        # state_variations (all have been excluded but one). In which
        # case we are done.
        if n_jobs == 0:
            logger.info("Did not find any state variations to test: We are done.");
            break;

        # Wait for the results
        while n_jobs > 0:
            result = result_queue.get(block=True);
            n_jobs -= 1;

            job_flags, state_variation, score = result;

            # FIXME: This should trigger some kind of assertion failure.
            if score is None:
                score = float('inf');

            flag_idx, other_state = state_variation;

            # Save to file
            print("{},{}".format(" ".join(job_flags), score),
                  file=f_live_global_leaderboard);
            f_live_global_leaderboard.flush();

            # print("state_variation_and_scores: {}".format(state_variation_and_scores));
            # print("looking for: {}, {}".format(flag_idx, other_state));

            idxes = [i for i, e in enumerate(state_variation_and_scores) if e[0][0] == flag_idx and e[0][1] == other_state];
            # debug("idxes: {}".format(idxes));

            state_variation_and_scores[idxes[0]] = (state_variation, score);

        # Now sort the list, with best state variation at the top and
        # worst the worst at the bottom.
        state_variation_and_scores.sort(key=lambda e: e[1]);

        # Write out to file for debugging
        with open(os.path.join(run_directory, "iteration.{}".format(n_iterations)), "w") as file:
            print("current flags: {}".format(" ".join(create_cmd_from_flaglist(baseline_config))), file=file);
            print("baseline: {}".format(baseline), file=file);

            print("State variations:", file=file);

            for state_variation, score in state_variation_and_scores:
                flag_idx, state = state_variation;
                print("{},{}".format(config.flags[flag_idx].values[state], score), file=file);

        # Also write out the baseline flags to a separate file for ease of use
        with open(os.path.join(run_directory, "iteration.{}.flags".format(n_iterations)), "w") as file:
            print(" ".join(create_cmd_from_flaglist(baseline_config)), file=file);

        with open(os.path.join(run_directory, "iteration.{}.config".format(n_iterations)), "w") as file:
            print(json.dumps(obj=baseline_config, indent=4, cls=Config.JSONEncoder), file=file);

        # Now, we can do something to the baseline set of flags with
        # this information.

        # ...If noone beat the baseline, then actually we don't have any more work to do.

        have_better_than_baseline_p = False;
        for state_variation, score in state_variation_and_scores:
            if score < baseline:
                have_better_than_baseline_p = True;
                break;

        if not have_better_than_baseline_p:
            logger.info("Iteration {}: No state variable variation managed to beat the current baseline of {}: Exiting."\
                 .format(n_iterations, baseline));
            break;

        # Exclude some flags from the worst states.
        # MAX_EXCLUSIONS = 3;
        # to_exclude = min(MAX_EXCLUSIONS, len(state_variation_and_scores));
        #
        # for state_variation, score in state_variation_and_scores[-to_exclude:]:
        #     flag_idx, other_state = state_variation;
        #     config.flags[flag_idx].exclusions = config.flags[flag_idx].exclusions.union({other_state});

        if args.drop_pessimizing_flags:
            for state_variation, score in state_variation_and_scores:
                if score < baseline:
                    flag_idx, other_state = state_variation;
                    config.flags[flag_idx].exclusions = config.flags[flag_idx].exclusions.union({other_state});

        improved_state_variation_and_scores = [e for e in state_variation_and_scores if e[1] > baseline];

        # Promote some flags to the best states.
        MAX_PROMOTIONS = 1;
        to_promote = min(MAX_PROMOTIONS, len(improved_state_variation_and_scores));
        have_promoted = [];

        for state_variation, score in improved_state_variation_and_scores[0 : to_promote]:
            flag_idx, other_state = state_variation;

            # We don't want to re-promote a flag index that we've
            # already promoted - that would be a de-motion!
            if flag_idx in have_promoted:
                continue;

            # If we have fewer better scores than to_promote, exit early.
            if baseline <= score:
                break;

            have_promoted.append(flag_idx);

            # We don't want to go back to the old state... or do we?
            current_state = config.flags[flag_idx].state;
            config.flags[flag_idx].exclusions = config.flags[flag_idx].exclusions.union({current_state});
            config.flags[flag_idx].state = other_state;

        # Now that we've adjusted the current flag state, go to the next iteration.
        n_iterations += 1;

    # If we're here, we broke out of the loop because we have no more
    # work to do. Close workers, close queues, and exit.
    for idx, worker in enumerate(workers):
        work_queue.put(None);

    for idx, worker in enumerate(workers):
        logger.debug("Trying to exit Worker #{}...".format(idx));
        worker.join();
        logger.debug("Exited Worker #{}".format(idx));

    work_queue.close();
    result_queue.close()

    logger.info("All done, tested {} flag combinations."\
                .format(n_tests));

    f_final_global_leaderboard = open(
        os.path.join(run_directory, "global_leaderboard.final"), "w");

    # info("Global leaderboard:");
    # for flagpath in global_leaderboard:
    #     info("\t{},{}".format(" ".join(flagpath), lookup_flag_from_flagpath(root, flagpath).score));
    #     print("{},{}".format(" ".join(flagpath), lookup_flag_from_flagpath(root, flagpath).score),
    #           file=f_final_global_leaderboard);

    #     f_final_global_leaderboard.flush();

    f_final_global_leaderboard.close();
    f_live_global_leaderboard.close();

def test_worker_context():
    from context.ExampleWorkerContext import ExampleWorkerContext;
    wc = ExampleWorkerContext(0, os.path.join(os.getcwd(), 'workspace', '0'));
    wc.init_workspace();
    wc.compile([]);
    wc.size();

def main():
    work();

if __name__ == "__main__":
    main();
