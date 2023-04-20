#!/usr/bin/env python3

# Program to show the leader board

# This file is part of SimpleTuner

# Copyright (C) 2021-2023 Embecosm <www.embecosm.com>
# Contributor Maxim Blinov <maxim.blinov@embecosm.com>

# SPDX-License-Identifier: GPL-3.0-or-later

import sys, os, re;

def main():
    results = [];

    with open(sys.argv[1], "r") as file:
        for line in file:
            line = line.strip();
            flags, score = line.split(",");
            results.append((flags, float(score)));

    results.sort(key=lambda x: x[1], reverse=False);

    print("Top 10 best flags of {}:".format(len(results)));

    for flags, score in results[:10]:
        if "SIMPLETUNER_COREMARKIFY" in os.environ:
            print("{} ({}): {}".format(score, round(1 / (float(score) * 1e-6), 2), flags));
        else:
            print("{}: {}".format(score, flags));

if __name__ == "__main__":
    main();
