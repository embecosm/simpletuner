import os, sys, re, subprocess;
import random;
import logging;
import time;

from simpletuner import CompileRequest;
from simpletuner import CompileResult;
from simpletuner import get_env_vc;
from simpletuner import get_checksum_for_filename;

class SweRVWorkerContext:
    def __init__(self, idx, workspace):
        self.idx = idx;
        self.workspace = workspace;

        self.env = os.environ.copy();
        self.env["RV_ROOT"] = self.workspace;

        self.re_ticks = re.compile(r"Total ticks      \: ([0-9]+)");

        self.march = "rv32imc";
        self.mabi = "ilp32";

        self.logger = logging.getLogger("SweRVWorkerContext#{}".format(idx))

    def init_workspace(self):
        self.logger.debug("Creating workspace in {}".format(self.workspace));

        if "SWERV_SOURCE_TAR" not in os.environ:
            self.logger.error("Please set the environment variable \"SWERV_SOURCE_TAR\""
                              " to contain the path to a prebuilt Cores-SweRV.");
            return False;

        self.SOURCE_TAR = os.environ["SWERV_SOURCE_TAR"];

        cmd = ["tar", "-xf", self.SOURCE_TAR,
               "--directory", self.workspace];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            self.logger.error("init_workspace(): Failed to extract:" \
                              .format(self.idx, file=sys.stderr));
            self.logger.error(stderr.decode("utf-8").strip());
            return False;

        return True;

    def better(x, y):
        # Return True if score `x` is better than score `y`
        return x < y;

    def worst_possible_result():
        # Return the worst possible result that is still
        # sortable. This is used internally to deal with tests that
        # fail, and thus should be pessimized as much as possible from
        # being selected to run again.
        return float('inf');

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
            self.logger.error("compile(): Failed to clean directory:");
            self.logger.error(stderr.decode("utf-8").strip());
            return CompileResult(False, None);

        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
                "GCC_PREFIX=riscv32-unknown-elf",
                "target=high_perf", "TEST=cmark_iccm",
                "TEST_CFLAGS={}".format(" ".join(["-march=" + self.march,
                                                  "-mabi=" + self.mabi,
                                                  "-Ofast"] + flags \
                                                 + ["-fno-exceptions", "-fno-asynchronous-unwind-tables"])),
                "program.hex"];

        self.logger.debug("compile(): Executing \"{}\"" \
                          .format(" ".join(make)));

        res = subprocess.Popen(make, cwd=self.workspace, env=self.env,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            self.logger.error("[{}]: compile(): Failed to compile:" \
                              .format(self.workspace));
            self.logger.error(stderr.decode("utf-8").strip());
            return CompileResult(False, None);

        # Get the checksum
        checksum = get_checksum_for_filename(os.path.join(self.workspace, "cmark_iccm.exe"));

        return CompileResult(True, checksum);

    def benchmark(self):
        return self.run();

    def run(self):
        make = ["make", "-f", "tools/Makefile",
                "RV_ROOT={}".format(self.workspace),
                "GCC_PREFIX=riscv32-unknown-elf",
                "target=high_perf", "TEST=cmark_iccm",
                "verilator"];

        self.logger.debug("run(): Executing \"{}\"" \
                          .format(" ".join(make)));

        res = subprocess.Popen(make, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        if res.returncode != 0:
            self.logger.warn("Failed to run:");
            self.logger.warn(stderr.decode("utf-8"));
            return None;

        score = None;
        for line in stdout.decode("utf-8").split('\n'):
            line = line.strip();

            mo = self.re_ticks.match(line)
            if not mo:
                continue;

            score = int(mo.group(1));

        if score is None:
            self.logger.warn(
                "[{}]: run(): Failed to find score: Either the benchmark failed to execute correctly, or the verilator model cycle timeout threshold was reached.".format(
                    self.workspace));

        else:
            self.logger.debug("[{}]: run(): Got score \"{}\"" \
                              .format(self.workspace, str(score)));

        return score;

    def size(self):
        cmd = ["riscv32-unknown-elf-size", "./cmark_iccm.exe"];

        res = subprocess.Popen(cmd, cwd=self.workspace,
                               stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE);

        stdout, stderr = res.communicate();

        # debug("size stdout: ", stdout);
        # debug("size stderr: ", stderr);

        lines = [line.strip() for line in stdout.decode("utf-8").split('\n')];
        fields = [field.strip() for field in lines[1].split()];

        text = int(fields[0]);
        data = int(fields[1]);
        bss = int(fields[2]);

        return text;
