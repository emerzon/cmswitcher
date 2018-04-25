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
pool_list = {"zpool": "http://www.zpool.ca/api/status",
             "ahashpool": "https://www.ahashpool.com/api/status/"}
minimum_daily_profitability = 0.001
benchmark_timeout = 45
possible_references = ["estimate_current", "estimate_last24h", "actual_last24h"]

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
    print "Benchmarking algorithm %s for %s seconds... " % (algo, benchmark_timeout)
    results = []
    try:
        for line in cpuminer("-a", algo, "--benchmark", _timeout=benchmark_timeout, _iter=True):
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


    for k, v in pool_list.iteritems():
        pool_list_with_data[k] = requests.get(v).json()

        # Unit normalization
        if k == "zpool":
            for algo in pool_list_with_data[k]:
                for field in possible_references:
                    # These algos are rated in TH/s
                    if algo in ["sha256"]:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000000000000
                    # These algos are rated in GH/s
                    elif algo in ["scrypt", "blakecoin", "decred", "x11", "quark", "qubit",  "sha256t", "keccak", "keccakc", "blake2s"]:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000000000
                    # These algos are rated in KH/s
                    elif algo in ["equihash"]:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000
                    # By default, all other algos are MH/s
                    else:
                        pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000000
    #* values in mBTC/Mh/day (mBTC/Gh/day for blake2s|blakecoin|quark|qubit|scrypt|x11, mBTC/Kh/day for yescrypt)
        if k == "ahashpool":
            # These algos are rated in GH/s
            if algo in ["blake2s", "blakecoin", "quark", "qubit", "scrypt", "x11"]:
                pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000000000
            # These algos are rated in KH/s
            elif algo in ["yescrypt"]:
                pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000
            # By default, all other algos are MH/s
            else:
                pool_list_with_data[k][algo][field] = float(pool_list_with_data[k][algo][field]) / 1000000

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
            for rentability_tag in possible_references:

                if algo in benchmarked_algos and benchmarked_algos[algo] > 0:
                    local_hashrate = float(benchmarked_algos[algo])
                    pool_current_estimate = float(pool_info[pool][algo][rentability_tag])
                    value_per_day = local_hashrate * pool_current_estimate * mbitcoin_value
                    if value_per_day >= minimum_daily_profitability:
                        algos_with_profit.append([pool, algo, rentability_tag, value_per_day])

    for pool, algo, rentability_tag, value_per_day in sorted(algos_with_profit, key=lambda x: x[3], reverse=True):
        print "%s | %s | %s |  USD %s/day" % (pool, algo, rentability_tag, '{:,.4f}'.format(value_per_day))

