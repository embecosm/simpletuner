# Example worker context

# This file is part of SimpleTuner

# Copyright (C) 2021-2023 Embecosm <www.embecosm.com>
# Contributor Maxim Blinov <maxim.blinov@embecosm.com>

# SPDX-License-Identifier: GPL-3.0-or-later

import os;
import random;
import logging;
import time;
import subprocess;

from common import CompileResult
from common import CompileRequest;
from common import get_checksum_for_filename;

class ExampleWorkerContext:
    MAIN_C = \
        """
        #include <stdio.h>

        #define ELEMS (1 << 10)

        size_t elems = ELEMS;
        struct { float x, y, z, w; } src[ELEMS], dst[ELEMS];

        void work (void);

        int
        main (void)
        {
          for (int i = 0; i < 1E6; ++i)
            work ();

          return 0;
        }
        """;

    WORK_C = \
        """
        #include <stdio.h>

        extern size_t elems;
        extern struct { float x, y, z, w; } src[], dst[];

        void
        work (void)
        {
          for (size_t i = 0; i < elems; ++i)
            dst[i] = src[i];
        }
        """;

    # Return the "type" of benchmark your Worker supports.

    # This information will be used by the Simpletuner driver
    # to check the user-supplied --benchmark flag.
    @staticmethod
    def get_available_benchmark_types() -> list:
        return ["execution", "size"];

    def __init__(self, idx, workspace, cc, benchmark_type):
        # Create a logger
        self.logger = logging.getLogger("ExampleWorkerContext#{}".format(idx))

        # Absolute path to the C compiler, provided by the user via the `--cc` flag.
        self.cc = cc;

        # Our thread index
        self.idx = idx;

        # Absolute path to our workspace. We have free rein to do whatever we want here.
        self.workspace = workspace;

        # The 'type' of benchmark that will be running. This will be provided by the user via the `--benchmark` flag.
        self.benchmark_type = benchmark_type;

        random.seed(self.idx);

    # Initialise workspace, whatever that may be.
    # Simpletuner will call this function after it has created your directory and called
    # your `__init__` function. The `workspace` parameter provided earlier in
    # `__init__` is intended to be used here.
    #   Note that if you are running multi-process Simpletuner (e.g. `-j 4`), this
    # function may be running simultaneously across multiple processes.
    def init_workspace(self):
        self.logger.debug("Creating workspace in {}".format(self.workspace));

        with open(os.path.join(self.workspace, "main.c"), "w") as file:
            file.write(self.MAIN_C);

        with open(os.path.join(self.workspace, "work.c"), "w") as file:
            file.write(self.WORK_C);

        self.logger.info("Successfully setup workspace");
        return True;

    # Return `True` if score `x` is "better" than score `y`.
    # ----
    # Note that in this example, all the benchmark types' worst-case value is infinity.
    # But if you had for example, a `benchmark_type` that sought to maximise the No. of
    # bytes processed, or some other "bigger=better" type metric, then you would
    # put `return x > y` here.
    def better(self, x, y) -> float:
        if self.benchmark_type == "execution" or self.benchmark_type == "size":
            return x < y;


    # Return the worst possible result that is still sortable.
    # ----
    # This is used internally to deal with tests that
    # fail, and thus should be pessimized as much as possible from
    # being selected to run again.
    # The same logic applies here as in the `better(self, x, y)` function above.
    def worst_possible_result(self) -> float:
        if self.benchmark_type == "execution" or self.benchmark_type == "size":
            return float('inf');


    # Compile/clean/prepare your executable.
    # Simpletuner will call this function right before it calls your `benchmark` function.
    # ----
    # The compile step is broken out into a separate step in order to facilitate caching -
    # that is, if flag 'A' and flag 'B' both generate the exact same executable, it doesn't
    # make sense to run both, since they will both run the same way. In this case, Simpletuner
    # will skip the `benchmark` step for a flag for which it already has a cached entry.
    def compile(self, flags) -> CompileResult:
        cmd = [self.cc, "-o", "work", "main.c", "work.c"] + flags;

        self.logger.debug("[{}]: compile(): Executing \"{}\"" \
                          .format(self.workspace, " ".join(cmd)));

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            self.logger.error("[{}]: compile(): Exit code {}: Failed to compile:"\
                              .format(self.workspace, res.returncode));
            self.logger.error("stderr: \n" + stderr.decode("utf-8").strip());
            return CompileResult(False, None);

        # Calculate the checksum for this file. We _really_ want to do this,
        # as a lot of flags will have no effect on the binary, and this saves a lot of compute time.
        checksum = get_checksum_for_filename(os.path.join(self.workspace, "work"));

        return CompileResult(True, checksum);

    # Run whatever benchmark the user specified in `--benchmark`.
    #   Upon failure, Return `None`.
    #   Upon success, Return a floating-point arbitrary score value.
    def benchmark(self):
        if self.benchmark_type == "execution":
            return self.run();
        elif self.benchmark_type == "size":
            return self.size();
        else:
            # This should not be reachable - Make sure you sanity-check the
            # `benchmark_type` that is provided to you in the __init__ function.
            self.logger.error("Unreachable: self.benchmark_type: \"{}\" is invalid. Aborting"\
                              .format(self.benchmark_type));
            exit(1);

    def run(self):
        cmd = ["./work"];

        self.logger.debug("[{}]: run(): Executing \"{}\"" \
                          .format(self.workspace, " ".join(cmd)));

        start = time.time();

        timeout_sec = 30;
        did_timeout_p = False;

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        try:
            _, _ = res.communicate(timeout=timeout_sec);
        except subprocess.TimeoutExpired:
            did_timeout_p = True;

        if did_timeout_p:
            self.logger.error("run() step timed out");
            return None;

        if res.returncode != 0:
            self.logger.error("run() step failed to run: exit code {}".format(res.returncode));
            return None;

        end = time.time();
        delta = end - start;

        return delta;

    def size(self):
        return self.size_find_size_of_text_section();

    def size_find_size_of_text_section(self):
        cmd = ["size", "./work"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            return None;

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n')];
        fields = [field.strip() for field in lines[1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return float(text);
