#!/usr/bin/env python3
import os, sys, re, time, random, subprocess, shutil;

import multiprocessing as mp;

# See: https://stackoverflow.com/a/13941865 - we need this to catch
# `queue.Empty` exceptions
import queue; # Called "Queue" in Python 2

CC = "riscv32-unknown-elf-gcc";

def debug(*args, **kwargs):
    print("[DEBUG] " + " ".join(map(str,args)), **kwargs, file=sys.stderr);

def info(*args, **kwargs):
    print("[INFO] " + " ".join(map(str,args)), **kwargs, file=sys.stderr);

def warn(*args, **kwargs):
    print("[WARN] " + " ".join(map(str,args)), **kwargs, file=sys.stderr);

def fetch_gcc_params():
    params = {};

    re_param_bounded = re.compile(
        r"\-\-param\=([a-zA-Z0-9\-]+)\=<(\-?[0-9]+),(\-?[0-9]+)>\s+(\-?[0-9]+)");

    re_param_unbounded = re.compile(
        r"\-\-param\=([a-zA-Z0-9\-]+)\=\s+(\-?[0-9]+)");

    res = subprocess.Popen([CC, "--help=params", "-Q"],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    if res.returncode != 0:
        info("gcc exited with {}".format(res.returncode));
        sys.exit(1);

    stdout = stdout.decode("utf-8").strip();
    lines = stdout.split('\n');

    # The first line is always
    # ```
    #  The following options control parameters:
    #  ...
    # ```
    # So remove it.
    lines = lines[1:];

    for lineno, line in enumerate(lines):
        # Try matching a fully-constrained parameter, e.g.
        #   --param=uninit-control-dep-attempts=<1,65536>       1000
        mo = re_param_bounded.search(line);
        if mo:
            # print("Found groups: {}".format(",".join([mo.group(i) for i in range(len(mo.groups()))])));
            # print("Found groups: {}".format(",".join([str(i) for i in range(10)])));

            param_name = mo.group(1);
            param_range = (int(mo.group(2)), int(mo.group(3)));
            param_default = int(mo.group(4));

            # print("line {}: Parsed parameter \"{}\", range [{},{}], default {}"\
            #       .format(lineno, param_name, param_range[0], param_range[1],
            #               param_default));
            params[param_name] = {"min": param_range[0],
                                  "max": param_range[1],
                                  "default": param_default};
            continue;

        # Try matching an unconstrained parameter, e.g.
        #   --param=sra-max-propagations=         32
        mo = re_param_unbounded.search(line);
        if mo:
            param_name = mo.group(1);
            param_range = None;
            param_default = int(mo.group(2));

            # print("line {}: Parsed parameter \"{}\", unconstrained, default {}"\
            #       .format(lineno, param_name, param_default));
            params[param_name] = {"min": 0,
                                  "max": 2147483647,
                                  "default": param_default};
            continue;

        # If we're still here, it may be because we got a strange
        # --param flag, e.g.
        #
        #   --param=parloops-schedule=[static|dynamic|guided|auto|runtime]        static
        # or
        #   --param=lazy-modules=                 [available in C++]
        print("line {}: Unrecognized parameter \"{}\""\
              .format(lineno, line), file=sys.stderr);

    # Hack: The following params are bugged:
    # --param=logical-op-non-short-circuit
    # --param=vect-max-peeling-for-alignment

    # Because in the gcc/params.opt file it is specified as a
    # IntegerRange(-1, 1), but the command line parser treats it like
    # a UInteger. Hence, even though the default is -1, we can't
    # actually specify -1 at the command line without getting an
    # error. So lets omit it for now.

    if "logical-op-non-short-circuit" in params:
        params["logical-op-non-short-circuit"]["min"] = 0;

    if "vect-max-peeling-for-alignment" in params:
        params["vect-max-peeling-for-alignment"]["min"] = 0;

    # Causes GCC to crash if we set this to too high a value. Probably
    # not relevant to optimisation anyway.
    if "min-nondebug-insn-uid" in params:
        del params["min-nondebug-insn-uid"];

    # Remove flags which are hopefully irrelevant to speed
    # optimisation
    to_removes = [
        "asan-globals",
        "asan-instrument-allocas",
        "asan-instrument-reads",
        "asan-instrument-writes",
        "asan-instrumentation-with-call-threshold",
        "asan-memintrin",
        "asan-stack",
        "asan-use-after-return",
        "hwasan-instrument-stack",
        "hwasan-random-frame-tag",
        "hwasan-instrument-allocas",
        "hwasan-instrument-reads",
        "hwasan-instrument-writes",
        "hwasan-instrument-mem-intrinsics",

        "cxx-max-namespaces-for-diagnostic-help",

        "ggc-min-expand",
        "ggc-min-heapsize",
        
        "graphite-allow-codegen-errors",
        "hash-table-verification-limit",

        "lazy-modules",
        
        "lto-max-partition",
        "lto-max-streaming-parallelism",
        "lto-min-partition",
        "lto-partitions",

        # OMP is probably not relevant
        "parloops-chunk-size",
        "parloops-min-per-thread",

        "profile-func-internal-id",
        "tm-max-aggregate-size",
        "tracer-dynamic-coverage",
        "tracer-dynamic-coverage-feedback",
        "tracer-max-code-growth",
        "tracer-min-branch-probability",
        "tracer-min-branch-probability-feedback",
        "tracer-min-branch-ratio",

        "tsan-distinguish-volatile",
        "tsan-instrument-func-entry-exit",

        "use-canonical-types"
    ];

    for to_remove in to_removes:
        if to_remove in params:
            del params[to_remove];

    # print("Got stdout:\n", "\n".join(lines));
    return params;

def fetch_gcc_optimizations():
    flags = [];

    re_param_simple = re.compile(r"\-f([a-zA-Z0-9\-]+)\s+");

    res = subprocess.Popen([CC, "--help=optimizers", "-Q"],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    if res.returncode != 0:
        error("[ERROR] gcc exited with {}".format(res.returncode));
        sys.exit(1);

    stdout = stdout.decode("utf-8").strip();
    lines = stdout.split('\n');

    # The first line is always
    # ```
    #  The following options control parameters:
    #  ...
    # ```
    # So remove it.
    lines = lines[1:];

    for lineno, line in enumerate(lines):
        # Try matching a simple flag, e.g.
        #     -ftree-partial-pre                    [disabled]
        mo = re_param_simple.search(line);
        if mo:
            # print("Found groups: {}".format(",".join([mo.group(i) for i in range(len(mo.groups()))])));
            # print("Found groups: {}".format(",".join([str(i) for i in range(10)])));
            flag_name = mo.group(1);

            # print("line {}: Parsed parameter \"{}\", range [{},{}], default {}"\
            #       .format(lineno, param_name, param_range[0], param_range[1],
            #               param_default));
            flags.append("-f" + flag_name);
            flags.append("-fno-" + flag_name);

            continue;

        # If we're still here, it may be because we got a strange
        # flag, e.g.
        #
        #   -fvect-cost-model=[unlimited|dynamic|cheap|very-cheap]        [default]
        # or
        #     -flifetime-dse=<0,2>                  2
        print("line {}: Unrecognized parameter \"{}\"".format(lineno, line), file=sys.stderr);

    # Remove flags which are hopefully irrelevant to speed
    # optimisation
    to_removes = [
    ];

    for to_remove in to_removes:
        try:
            flags.remove(to_remove);
        except ValueError:
            continue;

    # print("Got stdout:\n", "\n".join(lines));
    return flags;

def flatten_params(params):
    flags = [];

    for k, v in params.items():
        if v["min"] is None:
            # print("Skipping {} as it is unbounded".format(k), file=sys.stderr);
            # continue;
            pass;

        else:
            print("Expanding {}: (default: --param={}={})"\
                  .format(k, k, v["default"]), file=sys.stderr);

        # Treat the unbounded parameters specially
        unbounded_p = v["min"] == 0 and v["max"] == 2147483647;

        if unbounded_p:
            if v["default"] == 0:
                for i in range(0, 110, 10):
                    flags.append("--param={}={}".format(k, i));

            else:
                half_range = v["default"];
                full_range = half_range * 2;
                for i in range(0, full_range + 1,
                               full_range // 10 if full_range >= 10 else 1):
                    flags.append("--param={}={}".format(k, i));
                    
            continue;

        n_options = v["max"] - v["min"] + 1;

        if n_options <= 10:
            for i in range(v["min"], v["max"] + 1):
                flags.append("--param={}={}".format(k, i));
        else:
            # `... v["max"]` is correct - do the `v["max"] + 1` case
            # explicitly, so we can guarantee to always test it

            for i in range(v["min"], v["max"], n_options // 10):
                flags.append("--param={}={}".format(k, i));

            # Make sure we always test the maximum value
            flags.append("--param={}={}".format(k, v["max"]));

    return flags;

def fetch_all_gcc_flags():
    flags = [];
    
    # Fetch parameters
    params = fetch_gcc_params();
    flags += flatten_params(params);

    # Fetch optimisation flags
    flags += fetch_gcc_optimizations();

    return flags;

def check_gcc_flag(flag):
    cmd = [CC,
           "-fno-diagnostics-color",
           "-S", "-o", "/dev/null", flag,
           "-x", "c", "-"];

    res = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE);

    stdout, stderr = res.communicate();

    return (flag, res.returncode);

# def read_flags_file(path):
#     flags = [];

#     with open(path, "r") as file:
#         lines = [line.strip() for line in file];

#     with mp.Pool() as pool:
#         results = pool.map(check_flag, lines);

#     for idx, result in enumerate(results):
#         returncode, stderr = result;
#         flag = lines[idx];

#         if returncode != 0:
#             print("[WARN]: Flag \"{}\" failed to compile with the following error:".format(flag), file=sys.stderr);
#             print(stderr);
#             continue;

#         flags.append(flag);

#     return flags;

class WorkerContext:
    SOURCE_TAR = "/home/maxim/prj/opentuner/looper/looper.tar";

    def __init__(self, idx, workspace):
        self.idx = idx;
        self.workspace = workspace;

    def init_workspace(self):
        print("[DEBUG] Worker #{}: Creating workspace in {}"\
              .format(self.idx, self.workspace), file=sys.stderr);

        cmd = ["tar", "-xf", WorkerContext.SOURCE_TAR,
               "--directory", self.workspace];
        
        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            print("[ERROR] Worker #{}: init_workspace(): Failed to extract:"\
                  .format(self.idx, file=sys.stderr), file=sys.stderr);
            print(stderr.decode("utf-8").strip());
            return False;

        return True;
    
    def compile(self, flags):
        cmd = [CC, "-Ofast", "-o", "looper", "main.c", "work.c"] + flags;
        
        print("[DEBUG] Worker #{} [{}]: compile(): Executing \"{}\""\
              .format(self.idx, self.workspace, " ".join(cmd)), file=sys.stderr);

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            print("[ERROR] Worker #{} [{}]: compile(): Failed to compile:"\
                  .format(self.idx, self.workspace, file=sys.stderr));
            print(stderr.decode("utf-8").strip());
            return False;

        return True;

    def run(self):
        cmd = ["./looper"];

        start = time.time();
        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        end = time.time();
        delta = end - start;

        if res.returncode != 0:
            return None;
        
        return delta;

    def size(self):
        cmd = ["size", "./looper"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();
        print("size stdout: ", stdout);
        print("size stderr: ", stderr);

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n')];
        fields = [field.strip() for field in lines[1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return text;

class SweRVWorkerContext:
    SOURCE_TAR = "/home/ubuntu/prj/simpletuner/Cores-SweRV.tar.gz";

    def __init__(self, idx, workspace):
        self.idx = idx;
        self.workspace = workspace;
        self.env = os.environ.copy();
        self.env["RV_ROOT"] = self.workspace;
        self.re_ticks = re.compile(r"Total ticks      \: ([0-9]+)");

        self.march = "rv32imc";
        self.mabi = "ilp32";

    def init_workspace(self):
        print("[DEBUG] Worker #{}: Creating workspace in {}"\
              .format(self.idx, self.workspace), file=sys.stderr);

        cmd = ["tar", "-xf", self.SOURCE_TAR,
               "--directory", self.workspace];
        
        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            print("[ERROR] Worker #{}: init_workspace(): Failed to extract:"\
                  .format(self.idx, file=sys.stderr), file=sys.stderr);
            print(stderr.decode("utf-8").strip());
            return False;

        return True;
    
    def compile(self, flags):
        clean = ["rm", "-f",
                 "cmark_iccm.dis",
                 "cmark_iccm.exe",
                 "cmark_iccm.map",
                 "cmark.o",
                 "crt0.cpp.s",
                 "crt0.o",
                 "printf.o",
                 "exec.log",
                 "program.hex"];

        res = subprocess.Popen(clean, cwd=self.workspace, env=self.env,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            print("[ERROR] Worker #{} [{}]: compile(): Failed to clean directory:"\
                  .format(self.idx, self.workspace, file=sys.stderr));
            print(stderr.decode("utf-8").strip());
            return False;

        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
               "GCC_PREFIX=riscv32-unknown-elf",
               "target=high_perf", "TEST=cmark_iccm",
                "TEST_CFLAGS={}".format(" ".join(["-march=" + self.march,
                                                  "-mabi=" + self.mabi,
                                                  "-Ofast"] + flags)),
                "program.hex"];

        print("[DEBUG] Worker #{} [{}]: compile(): Executing \"{}\""\
              .format(self.idx, self.workspace, " ".join(make)), file=sys.stderr);

        res = subprocess.Popen(make, cwd=self.workspace, env=self.env,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            print("[ERROR] Worker #{} [{}]: compile(): Failed to compile:"\
                  .format(self.idx, self.workspace, file=sys.stderr));
            print(stderr.decode("utf-8").strip());
            return False;

        return True;

    def run(self):
        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
               "GCC_PREFIX=riscv32-unknown-elf",
               "target=high_perf", "TEST=cmark_iccm",
                "verilator"];

        res = subprocess.Popen(make, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            warn("Failed to run:");
            warn(stderr.decode("utf-8"));
            return None;

        score = None;
        for line in stdout.decode("utf-8").split('\n'):
            line = line.strip();

            mo = self.re_ticks.match(line)
            if not mo:
                continue;

            score = int(mo.group(1));
        
        if score is None:
            warn("Failed to run");
        else:
            print("[DEBUG] Worker #{} [{}]: run(): Got score \"{}\""\
                  .format(self.idx, self.workspace, str(score)), file=sys.stderr);

        return score;

    def size(self):
        cmd = ["riscv32-unknown-elf-size", "./cmark_iccm.exe"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();
        print("size stdout: ", stdout);
        print("size stderr: ", stderr);

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n')];
        fields = [field.strip() for field in lines[1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return text;

def better(x, y):
    # True if `x` is "better" than `y`
    return x < y;

class Flag:
    def __init__(self, flag, flags):
        self.flags = flags;
        self.flag = flag;
        self.score = None;
        self.children = dict();

    def __str__(self):
        return "" if self.flag is None else self.flag;

    def create_iterator(self):
        items = list(filter(lambda flag: (flag not in self.children or \
                                          self.children[flag].score is None), self.flags));

        if self.flag is None:
            return iter(items);

        idx = self.flags.index(str(self));
        return iter(items[idx+1:]);

def lookup_parent_flag_from_flagpath(root, flagpath):
    assert(isinstance(flagpath, list));
    
    if len(flagpath) == 0:
        return None;
    
    elif len(flagpath) < 2:
        if flagpath[0] not in root.children:
            walker.children[flagpath[0]] = Flag(flagpath[0], root.flags);

        if len(flagpath) == 1:
            return root;
    
    parent = root;
    child = parent.children[flagpath[0]];

    for flag in flagpath[1:]:
        if flag not in child.children:
            child.children[flag] = Flag(flag, root.flags);

        parent = child;
        child = child.children[flag];

    return parent;

def lookup_flag_from_flagpath(root, flagpath):
    assert(isinstance(flagpath, list));
    
    if len(flagpath) == 0:
        return root;

    walker = root;

    for flag in flagpath:
        if flag not in walker.children:
            walker.children[flag] = Flag(flag, root.flags);

        walker = walker.children[flag];

    return walker;

def worker_func(worker_ctx, work_queue, result_queue):
    idx = worker_ctx.idx;
    debug("Worker #{}: Started".format(idx));
    
    while True:
        job = work_queue.get(block=True);

        if job is None:
            debug("Worker #{}: Exiting".format(idx));
            return;

        flagpath = job;
        debug("Worker #{}: Got job \"{}\"".format(idx, flagpath));

        compile_ok = worker_ctx.compile(flagpath);
        if compile_ok:
            debug("compile_ok is True, getting runtime...");
            score = worker_ctx.run();
        else:
            debug("compile_ok Failed");
            score = None;

        result = (flagpath, score);

        debug("Worker #{}: Got result {} for \"{}\""\
              .format(idx, result[1], result[0]));

        result_queue.put(result, block=False);

def create_job_from_flagpath(flagpath):
    return flagpath;

def work():
    n_tests = 0;
    n_core_count = mp.cpu_count();
    
    # All flags under consideration
    # flags = ["a", "b", "c", "d"];
    # flags = read_flags_file("/home/maxim/prj/opentuner/ssv2/flags");

    # Global leaderboard to record _all_ results
    global_leaderboard = [];

    # "active" leaderboard, which only records flags whose score was an
    # improvement on their parent flag's score.
    leaderboard = [];

    # The current best result on the leaderboard
    best_flagpath = None;

    work_queue = mp.Queue();
    result_queue = mp.Queue();

    ### Phase 1: Flag discovery
    # Before we go and run the "real" search routine, first we find
    # out what each flag does individually, what impact it has, and if
    # it works at all.
    flags = [];
    all_gcc_flags = fetch_all_gcc_flags();
    # all_gcc_flags = all_gcc_flags[-100:-1];

    with mp.Pool(n_core_count) as pool:
        all_gcc_flags_test_results = pool.map(check_gcc_flag, all_gcc_flags);

    for flag, returncode in all_gcc_flags_test_results:
        if returncode == 0:
            flags.append(flag);

    if len(flags) == 0:
        error("After testing \"{}\" flags for function, we're left with 0 working flags! Maybe you're missing the C compiler or something?");
        sys.exit(1);

    ### Phase 2: Flag performance measurement
    # We need to create the workers anyway...

    worker_workspace = os.path.join(os.getcwd(), 'workspace');
    if os.path.isdir(worker_workspace):
        shutil.rmtree(worker_workspace);

    os.mkdir(worker_workspace);
    for idx in range(n_core_count):
        os.mkdir(os.path.join(worker_workspace, str(idx)));

    worker_ctxs = [SweRVWorkerContext(idx,
                                      os.path.join(worker_workspace, str(idx)))
                   for idx in range(n_core_count)];

    debug("Creating {} workers".format(n_core_count));
    workers = [mp.Process(target=worker_func,
                          args=(worker_ctx, work_queue, result_queue))
               for worker_ctx in worker_ctxs];
    debug("Done creating {} workers".format(n_core_count));

    with mp.Pool(n_core_count) as pool:
        pool.map(SweRVWorkerContext.init_workspace, worker_ctxs);

    for idx, worker in enumerate(workers):
        debug("Starting worker#{}".format(idx));
        worker.start();

    debug("Started {} workers".format(n_core_count));

    if not os.path.isfile("flags.top"):
        # Now test individually all the flags that we've discovered.
        n_active_jobs = 0;
        results = [];

        for flag in flags:
            debug("putting {} on work queue...".format(flag));
            work_queue.put([flag]);
            n_active_jobs += 1;

        while n_active_jobs > 0:
            flagpath, score = result_queue.get(block=True);
            n_active_jobs -= 1;
            info("{} flag tests left".format(n_active_jobs));

            if score is None:
                if better(0.0, float('-inf')):
                    score = float('-inf');
                else:
                    score = float('inf');

            results.append((flagpath[0], score));

        # If `better` performance is lower numbers, sort ascending. otherwise,
        # sort descending. First element should be best performing.
        results.sort(key=lambda e: e[1], reverse=better(2, 1));

        flags = [flag for flag, score in results];

        # Root flag from which we will be searching
        root = Flag(None, flags);

        # Write out to disk just in-case
        if True:
            with open("flags.top", "w+") as flags_top:
                for flag, score in results:
                    print("{},{}".format(flag, score), file=flags_top);

    else:
        results = [];

        with open("flags.top", "r") as flags_top:
            for line in flags_top:
                line = line.strip();
                debug("Processing line \"{}\"".format(line));
                flag, score = line.split(',');
                results.append((flag, score));
        
        results.sort(key=lambda e: e[1], reverse=better(2, 1));

        flags = [flag for flag, score in results];

        # Root flag from which we will be searching
        root = Flag(None, flags);

    # Submit root flag for testing
    job = create_job_from_flagpath([]);
    info("Putting first job on queue");
    info("root flags: {}".format(root.flags));
    work_queue.put(job, block=False);
    n_active_jobs = 1;
    n_tests = 1;

    debug("Put one job on the queue \"{}\"".format(job));

    ### Enter main loop:
    f_global_leaderboard = open("global_leaderboard.live", "w");

    while True:
        debug("n_active_jobs: {}".format(n_active_jobs));
        debug("leaderboard: {}".format(leaderboard));
        debug("work_queue.empty(): {}".format(work_queue.empty()));
        debug("result_queue.empty(): {}".format(result_queue.empty()));

        # We're done
        if n_active_jobs == 0 \
           and len(leaderboard) == 0:
            # We have no more work to do
            debug("Trying to exit...");
            
            for idx, worker in enumerate(workers):
                work_queue.put(None);
            
            for idx, worker in enumerate(workers):
                debug("Trying to exit worker#{}".format(idx));
                worker.join();

            work_queue.close();
            result_queue.close()
            
            print("[INFO] All done, tested {} flag combinations."\
                  .format(n_tests));

            print("Global leaderboard:");
            for flagpath in global_leaderboard:
                print("\t{} {}".format(lookup_flag_from_flagpath(root, flagpath).score, flagpath));

            break;

        # We may have to block on the result queue, if:
        # 1) All execution threads have been given a job, and we need
        #    to wait for atleast one to return a result before we can
        #    submit more jobs.
        # 2) We've submitted all as-of-yet untested children.
        #    (`leaderboard` will be empty if all the current known
        #    flags have had all their children submitted for testing.)
        elif n_active_jobs == n_core_count \
           or len(leaderboard) == 0:
            result = result_queue.get(block=True);

        # Non-blocking read, for when we're not too fussed about
        # getting a result right now, because we will (probably) have
        # work items we can put anyway.
        else:
            try:
                result = result_queue.get_nowait();
            except queue.Empty:
                result = None;

        if result is not None:
            n_active_jobs -= 1;
            n_tests += 1;

            flagpath, score = result;

            # All we are responsible for doing here is updating the
            # score in the tree, and updating the leaderboard (if the
            # score is better than the parent.)
            flag = lookup_flag_from_flagpath(root, flagpath);
            if score is not None:
                flag.score = score;

            else:
                # This indicates that the test failed. So we want to
                # give it the most pessimistic score possible, being
                # either -inf or inf - work out which.
                if better(0.0, float('-inf')):
                    flag.score = float('-inf');
                else:
                    flag.score = float('inf');

            parent_flag = lookup_parent_flag_from_flagpath(root, flagpath);
            debug("Got parent_flag \"{}\" for flagpath \"{}\"".format(parent_flag, flagpath));

            # Special case: if `flagpath` is `[]` (i.e. we have
            # received the result for testing the `root` flag), then
            # we have no `parent_flag`, and we by-definition put it on
            # the `leaderboard` (which by-defintion must be empty at
            # this point.)
            if parent_flag is None:
                leaderboard.append([]);
                debug("L164: Leaderboard: {}".format(leaderboard));

            else:
                if better(flag.score, parent_flag.score):
                    # FIXME: sorted insert
                    leaderboard.append(flagpath);
                    leaderboard.sort(key=lambda path: lookup_flag_from_flagpath(root, path).score);
                    debug("Added \"{}\" to leaderboard".format(flagpath));
                else:
                    debug("Child flag \"{}\" ({}) is not better than \"{}\" ({}), skipping"\
                          .format(flagpath, flag.score, flagpath[:-1], parent_flag.score));

            # Always store the result in the `global_leaderboard`
            # FIXME: sorted insert
            print(" ".join(flagpath) + ","\
                  + str(lookup_flag_from_flagpath(root, flagpath).score),
                  file=f_global_leaderboard);
            f_global_leaderboard.flush();

            global_leaderboard.append(flagpath);
            global_leaderboard.sort(key=lambda path: lookup_flag_from_flagpath(root, path).score);

        # Pick best from leaderboard
        # NOTE: If leaderboard is empty, that just means that:
        #   1). we have exhausted whatever parents we had, AND
        #   2). all of their children that have been scheduled have either
        #       resolved and failed to beat the parent, or haven't resolved yet.
        # if thats the case, then we just need to go back up and blocking-wait.
        if len(leaderboard) == 0:
            continue;
        
        current_best_flagpath = leaderboard[0];

        # If the best flag is now different, switch to exploring it instead.
        if best_flagpath != current_best_flagpath:
            best_flagpath = current_best_flagpath;
            
            best_flag = lookup_flag_from_flagpath(root, best_flagpath);
            
            best_flag_children_iterator = best_flag.create_iterator();

        # Get next job
        have_next_flag_p = False;
        try:
            next_child_flag = next(best_flag_children_iterator);
            have_next_flag_p = True;
            
        except StopIteration:
            # We have exhausted the `best_flag`'s immediate search space
            # (but not neccesarily its children's children search space).
            # Remove the flag this flag iterator belongs to from the
            # leaderboard.

            leaderboard.remove(best_flagpath);
            debug("Removed \"{}\" from leaderboard as it is exhausted"\
                  .format(best_flagpath));
            debug("Leaderboard now:");
            for item in leaderboard:
                print("\t" + str(item));
            
            # At this point, go back up and loop again. P.S. if leaderboard is empty now,
            # then we'll block on the next iteration.
            continue;

        # If we're here, we got a `next_child_flag`.
        debug("next_child_flag: {}".format(best_flagpath + [next_child_flag]));
        
        # We must have spare compute capacity here, otherwise we would have
        # blocked at the very beginning.
        if have_next_flag_p:
            job = create_job_from_flagpath(best_flagpath + [next_child_flag]);
            work_queue.put(job);
            n_active_jobs += 1;

        # We're done, go back up.

    return;

def dump_children(flag):
    it = flag.create_iterator();

    while True:
        try:
            item = next(it);
            print("Got item: {}".format(item));
        except StopIteration:
            print("Got StopIteration");
            break;

def test_flags():
    # All flags under consideration
    flags = ["a", "b", "c", "d"];

    # Root flag from which we will be searching
    root = Flag("", flags);
    it = root.create_iterator();

    dump_children(root);

    flag = lookup_flag_from_flagpath(root, ["a"]);
    dump_children(root);
    
    flag = lookup_flag_from_flagpath(root, ["c"]);
    dump_children(root);

    flag = lookup_flag_from_flagpath(root, ["c", "d"]);
    dump_children(root);

    parent = lookup_parent_flag_from_flagpath(root, ["c"]);
    dump_children(parent);

    parent = lookup_parent_flag_from_flagpath(root, ["c", "d"]);
    dump_children(parent);

def test_worker_context():
    wc = WorkerContext(0, os.path.join(os.getcwd(), 'workspace', '0'));
    wc.init_workspace();
    wc.compile([]);
    wc.size();

def main():
    work();

if __name__ == "__main__":
    main();
