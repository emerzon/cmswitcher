# This is the cpuminer switcher script by emerzonx (emerson.gomes@gmail.com)
#
# It will:
#  - Figure out which algos are supported by your cpuminer version
#  - Benchmark all of the supported algorithms and save the result to a file
# Soon enough it will:
#  - Perform algo/pool switching based on profitability

###
import sh
from sh import cpuminer
import json

def cpuminer_find_supported_algo():
    out = cpuminer("--help")
    add_line_to_result = False
    results = []
    for line in out:
        if line.strip().startswith("-o"):
            add_line_to_result = False
        if add_line_to_result:
            results.append(line.split()[0])
        if line.strip().startswith("-a"):
            add_line_to_result = True
    return results


def cpuminer_perform_benchmark(algo):
    value = 0
    timeout = 30
    print "Benchmarking algorithm %s for %s seconds... " % (algo, timeout)
    results = []
    try:
        for line in cpuminer("-a", algo, "--benchmark", _timeout=timeout, _iter=True):
            #print line
            if "Total" in line:
                value = line.split(',')[1]
                hashrate = normalize_hashrate(value.split()[0], value.split()[1])
                results.append(hashrate)
                print "... %s hashrate: Actual %s (Avg %s, Max %s)" % (algo, hashrate, median(results), max(results))

    except sh.TimeoutException:
        print "...terminated."

    if len(results) < 1:
        print "[ERROR] Couldn't get data, try increasing test timeout"
        return False
    else:
        return max(results)


def normalize_hashrate(hashrate, suffix):
    size = float(hashrate)
    suffix = suffix.lower()

    if suffix == "h/s":
        return size
    elif suffix == 'kh/s':
        return size * 1024
    elif suffix == 'mh/s':
        return size * 1024 * 1024
    elif suffix == 'gh/s':
        return size * 1024 * 1024 * 1024
    else:
        return False


def median(lst):
    n = len(lst)
    if n < 1:
        return None
    if n % 2 == 1:
        return sorted(lst)[n // 2]
    else:
        return sum(sorted(lst)[n // 2 - 1:n // 2 + 1]) / 2.0


def run_all_benchmarks(skip_existing):

    for algo in cpuminer_find_supported_algo():
    print cpuminer_perform_benchmark(algo)
