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
import requests

# Static data
blacklisted_algos = []
pool_list = {"zpool": "http://www.zpool.ca/api/status"}
minimum_daily_profitability = 0.001


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
            # print line
            if "Total" in line:
                value = line.split(',')[1]
                hashrate = normalize_hashrate(value.split()[0], value.split()[1])
                results.append(hashrate)
                print "... %s hashrate: Actual %s (Avg %s, Max %s)" % (algo, hashrate, median(results), max(results))

    except:
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
        return size * 1000
    elif suffix == 'mh/s':
        return size * 1000 * 1000
    elif suffix == 'gh/s':
        return size * 1000 * 1000 * 1000
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
    try:
        benchmarks = json.load(open('benchmarks.json'))
        print "Reading existing benchmarks.json"
    except:
        print "File benchmarks.json does not exist, creating a new one."
        benchmarks = {}
    for algo in cpuminer_find_supported_algo():
        if (algo not in benchmarks.keys() or not skip_existing) and algo not in blacklisted_algos:
            benchmarks[algo] = cpuminer_perform_benchmark(algo)
            json.dump(benchmarks, open('benchmarks.json', 'w'), sort_keys=True, indent=4, separators=(',', ': '))
            print "Updated benchmarks.json!"
    return benchmarks


def fetch_pool_info():
    pool_list_with_data = {}
    fields_to_parse = ["estimate_current", "estimate_last24h", "actual_last24h"]

    for k, v in pool_list.iteritems():
        pool_list_with_data[k] = requests.get(v).json()

        # Unit normalization for Zpool
        if k == "zpool":
            for algo in pool_list_with_data[k]:
                for field in fields_to_parse:
                    if algo in ["sha256"]:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000 / 1000 / 1000 / 1000
                    elif algo in ["scrypt", "blake", "decred", "x11", "quark", "qubit"]:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000 / 1000 / 1000
                    elif algo in ["equihash"]:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000
                    else:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000 / 1000


    return pool_list_with_data


def fetch_mbitcoin_value():
    value = requests.get("https://api.coindesk.com/v1/bpi/currentprice.json").json()
    return float(value['bpi']['USD']['rate'].replace(",", ""))/1000


if __name__ == "__main__":
    benchmarked_algos = run_all_benchmarks(True)
    pool_info = fetch_pool_info()
    mbitcoin_value = fetch_mbitcoin_value()
    algos_with_profit = []

    for pool, algos in pool_info.iteritems():
        for algo in algos:
            if algo in benchmarked_algos and benchmarked_algos[algo] > 0:
                local_hashrate = float(benchmarked_algos[algo])
                pool_current_estimate = float(pool_info[pool][algo]['actual_last24h'])
                value_per_day = local_hashrate * pool_current_estimate * mbitcoin_value
                if value_per_day >= minimum_daily_profitability:
                    algos_with_profit.append([algo, '{:,.4f}'.format(value_per_day)])

        for k, v in sorted(algos_with_profit, key=lambda x: x[1], reverse=True):
            print "%s - %s:USD %s / day" % (pool, k, v)

