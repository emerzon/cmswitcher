#!/usr/bin/env python3
import contextlib
import subprocess
import requests
import socket
import json
import time
from tabulate import tabulate
import argparse
import os

# Constants
API_PORT = 40101
API_HOST = "127.0.0.1"

# Read config
def load_config():
    try:
        with open("data/config.json") as f:
            config = json.load(f)
        with open("data/miners.json") as f:
            miners = json.load(f)
        with open("data/pools.json") as f:
            pools = json.load(f)
        with open("data/algos.json") as f:
            algos = json.load(f)
    except FileNotFoundError:
        print("Missing data files.")
        exit()
    return config, miners, pools, algos

config, miners, pools, algos = load_config()

# Inits
mbtc_value = 0

parser = argparse.ArgumentParser()
parser.add_argument(
    '--cpuminer', help='cpuminer binary location', default='cpuminer')
args = parser.parse_args()

# Check if cpuminer is available
if not os.path.isfile(args.cpuminer):
    print(f"cpuminer not found at {args.cpuminer}")
    exit()


def create_pool_params(pool, algo):
    pool_algo = find_pool_algo_name(pool, algo)
    return {
        "algo": algo,
        "wallet": pools[pool]["wallet"],
        "password": pools[pool]["password"],
        "url": pools[pool]["mine_url"].format(algo=pool_algo),
        "port": pools[pool]["results"][pool_algo]["port"]
    }

def create_cmdline(miner, algo, pool_params):
    if algo in miners[miner]["std_algos"]:
        launch_params = ["-a", algo]
    else:
        launch_params = []
        for k, v in miners[miner]["custom_algos"][algo].items():
            launch_params.extend((str(k), str(v)))
    cmdline = [args.cpuminer]
    cmdline += launch_params
    cmdline += miners[miner]["launch_pattern"].format(**pool_params).split(" ")
    return cmdline

def get_hashrate_and_shares():
    ret = get_api_data()
    if "HS" in ret.keys():
        hashrate = int(float(ret["HS"]))
    elif "KHS" in ret.keys():
        hashrate = int(float(ret["KHS"]) * 1000)
    accepted_shares = int(ret["ACC"])
    rejected_shares = int(ret["REJ"])
    return hashrate, accepted_shares, rejected_shares

def get_api_data():
    resp = ""

    # try to connect 3 times before giving up
    for _ in range(3):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", 40101))
            break
        except ConnectionRefusedError:
            print("Connection to miner API refused, retrying...")
            time.sleep(2)

    s.sendall(b'summary')
    while '|' not in resp:
        resp += s.recv(32).decode('utf-8')
    s.close()
    return dict((x.split("=") for x in resp.split(";")))


def find_pool_algo_name(pool, algo):
    result = None
    if algo in pools[pool]["results"].keys():
        result = algo
    else:
        for entry in pools[pool]["results"].keys():
            if entry.lower() == algo.lower():
                result = entry
    if result is None:
        for variation in algos:
            if algo in variation:
                for entry in variation:
                    if entry in pools[pool]["results"].keys():
                        result = entry
    return result


def pool_find_supported_algo(pool):
    print(f"Probing pool {pool}...", end="")
    pools[pool]["results"] = requests.get(pools[pool]["api"]).json()
    match = list(pools[pool]["results"].keys())
    print(f"{len(match)} algos supported")
    return match


def find_common_algos(list1, list2):
    results = {}
    for item1 in list1:
        if item1 in list2:
            results[item1] = item1
        else:
            for item2 in list2:
                if item1.lower() == item2.lower():
                    results[item1] = item2
                else:
                    for entry in algos:
                        # print (entry + " " + item1 + " " + item2)
                        if (item1 == entry) and (item2 == entry):
                            print(
                                f"Adding '{item1}' as a name variation of '{item2}'")
                            results[item1] = item2

    return results


def populate_supported_algos():
    for miner in miners.keys():
        print(f"Probing miner {miner}...", end="")
        miners[miner]["supported_algos"] = miners[miner]["std_algos"] + \
            list(miners[miner]["custom_algos"].keys())
        print(f'{len(miners[miner]["supported_algos"])} algos supported')
        print(miners[miner]["supported_algos"])

    for pool in pools.keys():
        pools[pool]["supported_algos"] = pool_find_supported_algo(pool)
        print(pools[pool]["supported_algos"])


def run_benchmark(miner, algo, pool, pool_params):

    if isinstance(pool_params, dict):
        print(f'Online benchmark for {miner} - {algo} on {pool_params["url"]}')
        cmdline = create_cmdline(miner, algo, pool_params)
        print(" ".join(cmdline))
        proc = subprocess.Popen(cmdline,
                                stdout=subprocess.PIPE)
    else:
        print(f"Offline benchmark for {miner} - {algo}")
        proc = subprocess.Popen([miner, '-a', algo] + miners[miner]
                                ["offline_bench"].split(" "), stdout=subprocess.PIPE)

    # print("Launched pid %s" % proc.pid)

    with contextlib.suppress(subprocess.TimeoutExpired):
        outs, errs = proc.communicate(timeout=5)
    if proc.returncode is not None:
        print("Miner crashed!! - Unsupported algo?")
        # print(str(outs), str(errs))
        return 0
    else:
        use_rate = benchmark(pool, algo, miner, proc)
    return use_rate


def benchmark(pool, algo, miner, proc):
    pool_algo = find_pool_algo_name(pool, algo)
    max_hashrate = 0
    accepted_shares = 0
    revenue = 0
    rejected_shares = 0
    t_end = time.time() + config["benchmark_period"]
    t_give_up = time.time() + config["give_up_benchmark_low_profit_secs"]
    while time.time() < t_end and \
            accepted_shares < config["complete_benchmark_min_shares"] and \
            (time.time() < t_give_up or revenue > config["min_profit"]) and \
            rejected_shares < config["max_rejected_shares"]:

        hashrate, accepted_shares, rejected_shares = get_hashrate_and_shares()

        if hashrate > max_hashrate:
            max_hashrate = hashrate
        if hashrate > 0:
            revenue = calc_pool_profitability(pool, pool_algo, hashrate)
        print(
            "[%s %s](%ss) Curr Profitability: USD %.4f Shares: %sA/%sR - Hashrate: %s/Max: %s                                \r" % (
                miner, algo, (int(t_end - time.time()) if revenue > config["min_profit"] else int(
                    t_give_up - time.time())), revenue, accepted_shares, int(rejected_shares), hashrate,
                max_hashrate), end="")
        time.sleep(1)
    proc.kill()
    print(
        f"[FINISHED]: Using hashrate {hashrate} for {algo} ({accepted_shares} accepted shares)                                                           "
    )
    result = hashrate
    if accepted_shares == 0:
        print("[WARNING]: No accepted shares!")

    return result


def fetch_mbitcoin_value():
    global mbtc_value
    if mbtc_value == 0:
        mbtc_value = requests.get(
            "https://api.coindesk.com/v1/bpi/currentprice.json").json()
    return float(mbtc_value['bpi']['USD']['rate'].replace(",", "")) / 1000


def run_all_benchmarks(skip_existing):
    for miner in miners:
        try:
            miners[miner]["benchmark"] = json.load(
                open(f'benchmark-{miner}.json'))
            print(f"Reading existing benchmark-{miner}.json")
        except Exception:
            print(
                f"File benchmark-{miner}.json does not exist, creating a new one.")
            miners[miner]["benchmark"] = {}

        for pool in pools:
            common_algos = find_common_algos(
                miners[miner]["supported_algos"], pools[pool]["supported_algos"])
            print(
                f"Miner {miner} and pool {pool} have {len(common_algos.keys())} algos in common"
            )
            for algo in common_algos.keys():
                if (algo not in miners[miner][
                        "benchmark"].keys() or not skip_existing) and algo not in config["blacklisted_algos"]:
                    # Launch bench here
                    pool_params = create_pool_params(pool, algo)
                    hashrate = run_benchmark(miner, algo, pool, pool_params)
                    miners[miner]["benchmark"][algo] = hashrate
                    json.dump(
                        miners[miner]["benchmark"],
                        open(f"benchmark-{miner}.json", 'w'),
                        sort_keys=True,
                        indent=4,
                        separators=(',', ': '),
                    )
                    print(f"Updated benchmark-{miner}.json !")


def calc_pool_profitability(pool, algo, hashrate):
    mbtc = fetch_mbitcoin_value()
    revenues = {}
    if algo in pools[pool]["results"].keys():
        fields = ['estimate_current', 'estimate_last24h']
        for field in fields:
            revenues[field] = (float(pools[pool]["results"][algo][field])*1000) * (
                (float(hashrate) / 1000000) / float(pools[pool]["results"][algo]["mbtc_mh_factor"])) * mbtc

        fields = ['actual_last24h']
        for field in fields:
            revenues[field] = float(pools[pool]["results"][algo][field]) * (
                (float(hashrate) / 1000000) / float(pools[pool]["results"][algo]["mbtc_mh_factor"])) * mbtc
    else:
        revenues = {'estimate_current': 0}
    return float(revenues['estimate_current'])


def get_current_profit_table():
    profit_table = []
    for miner in miners:
        for pool in pools:
            for algo in miners[miner]["benchmark"].keys():
                pool_algo = find_pool_algo_name(pool, algo)
                value = calc_pool_profitability(
                    pool, pool_algo, miners[miner]["benchmark"][algo])
                if value > config["min_profit"]:
                    profit_table.append(
                        [miner, pool, algo, "{0:.5f}".format(value)])
    return sorted(profit_table, key=lambda x: x[3], reverse=True)


if __name__ == "__main__":
    populate_supported_algos()
    benchmarked_algos = run_all_benchmarks(True)
    print(tabulate(get_current_profit_table()))

    # Start a session for the most profitable algo. After session_timeout, check if the algo is still the most profitable. If so, just loop. If not, restart the session.

    current_algo = ""
    proc = None
    while True:
        start_time = time.time()
        print (get_current_profit_table()[0])
        most_profitable_miner, most_profitable_pool, most_profitable_algo, _ = get_current_profit_table()[0]


        if current_algo != most_profitable_algo:
            if proc is not None:
                print(f"Switching away from {current_algo}")
                proc.kill()
            print(
                f"Starting to mine {most_profitable_algo} on {most_profitable_pool} with {most_profitable_miner}")
            current_algo = most_profitable_algo

            pool_params = create_pool_params(
                most_profitable_pool, most_profitable_algo)
            
            cmdline = create_cmdline(most_profitable_miner, most_profitable_algo, pool_params)

            print(" ".join(cmdline))
            proc = subprocess.Popen(cmdline,
                                    stdout=subprocess.PIPE)
            print(f"Launched pid {proc.pid}")

        while start_time + config["session_timeout"] > time.time():
            # Retrieve hashrate and profitability

            hashrate, accepted_shares, rejected_shares = get_hashrate_and_shares()

            revenue = calc_pool_profitability(
                most_profitable_pool, most_profitable_algo, hashrate)
            # limit revenue to 3 decimals
            revenue = float("{0:.3f}".format(revenue))
            print(
                f"Current profitability: {revenue} USD/day - Hashrate: {hashrate} - Shares: {accepted_shares}A/{rejected_shares}R", end="\r")
            time.sleep(1)            