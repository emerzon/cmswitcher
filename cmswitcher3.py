import subprocess
import re
import requests
import socket
import json
import time

benchmark_period = 120
min_shares = 2

miners = {"cpuminer": {"url": "https://chita.com.br/miners/cpuminer-%s.tar.bz2",
                       "launch_pattern": "-u {wallet} -o stratum+tcp://{url}:{port} -p {password} -b 127.0.0.1:40101",
                       "offline_bench_pattern": "--benchmark -b 127.0.0.1:40101"}}
pools = {"zergpool": {"api": "http://api.zergpool.com:8080/api/status",
                      "mine_url": "{algo}.mine.zergpool.com",
                      "wallet": "ME1xYgz1mtCTiJW7UMEP82S7NeQoJvwL7o",
                      "password": "c=LTC,sd=1"}}

algo_name_variations = [
    ['argon2d500', 'argon2d-dyn']
]

blacklisted_algos = []


def get_api_data():
    resp = ""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 40101))
    s.sendall(b'summary')
    while not '|' in resp:
        resp += s.recv(32).decode('utf-8')
    s.close()
    return {k: v for k, v in (x.split("=") for x in resp.split(";"))}


def get_cpuflags_hash():
    return []
    # This generates a unique 8-digit value which identifies this specific CPU capabilities
    # zen    = 5c6a2fc9
    # zen-tr = 0a8e7444
    # zen2   = 46b820de
    # 'cat /proc/cpuinfo | grep flags | uniq | md5sum | cut -b 1-8'


def miner_find_supported_algo(miner_name):
    print("Probing miner %s..." % miner_name, end="")
    if miner_name == 'cpuminer':
        out = subprocess.check_output(["cpuminer", "-h"]).decode("utf-8")
        # This is super ugly and might break in different versions... :(
        match = re.findall(r'(?!^\s*[-(].*$)^\s{20,26}(.*?)(?:\s).*$', out, re.MULTILINE)
    else:
        match = []
    print("%s algos supported" % len(match))
    return match


def pool_find_supported_algo(pool):
    print("Probing pool %s..." % pool, end="")
    pools[pool]["results"] = requests.get(pools[pool]["api"]).json()
    match = list(pools[pool]["results"].keys())
    print("%s algos supported" % len(match))
    return match


def find_common_algos(list1, list2):
    results = {}
    for item1 in list1:
        if item1 in list2:
            results.update({item1: item1})
        else:
            for item2 in list2:
                if item1.lower() == item2.lower():
                    results.update({item1: item2})
                else:
                    for entry in algo_name_variations:
                        if item1 in entry and item2 in entry:
                            results.update({item1: item2})
    return results


def populate_supported_algos():
    for miner in miners.keys():
        miners[miner]["supported_algos"] = miner_find_supported_algo(miner)
        # print(miners[miner]["supported_algos"])

    for pool in pools.keys():
        pools[pool]["supported_algos"] = pool_find_supported_algo(pool)
        # print(pools[pool]["supported_algos"])


def benchmark(miner, algo, pool_params):

    if isinstance(pool_params, dict):
        print("Online benchmark for %s - %s on %s" % (miner, algo, pool_params["url"]))
        proc = subprocess.Popen([miner, '-a', algo] + miners[miner]["launch_pattern"].format(**pool_params).split(" "), stdout=subprocess.PIPE)
    else:
        print("Offline benchmark for %s - %s" % (miner, algo))
        proc = subprocess.Popen([miner, '-a', algo] + miners[miner]["offline_bench"].split(" "), stdout=subprocess.PIPE)

    # print("Launched pid %s" % proc.pid)
    # UGLY HACK - To be fixed
    time.sleep(5)

    if proc.returncode is None:
        max_hashrate = 0
        accepted_shares = 0
        t_end = time.time() + benchmark_period
        while time.time() < t_end and accepted_shares < min_shares:
            ret = get_api_data()
            hashrate = float(ret["HS"])
            accepted_shares = int(ret["ACC"])
            if hashrate > max_hashrate:
                max_hashrate = hashrate
            print("[%s %s](%ss) Shares: %sA/%sR - Hashrate: %s/Max: %s                         \r" % (miner, algo, int(t_end-time.time()), accepted_shares, int(ret["REJ"]), hashrate, max_hashrate), end="")
            time.sleep(1)
        proc.kill()
        print("[FINISHED]: Using hashrate %s for %s (%s accepted shares)                             " % (max_hashrate, algo, accepted_shares))
        use_rate = max_hashrate
        if accepted_shares == 0:
            print("[WARNING]: No accepted shares!")
    else:
        print("Error launching miner")
        use_rate = False
    return use_rate


def fetch_mbitcoin_value():
    value = requests.get("https://api.coindesk.com/v1/bpi/currentprice.json").json()
    return float(value['bpi']['USD']['rate'].replace(",", "")) / 1000


def run_all_benchmarks(skip_existing):
    for miner in miners:
        try:
            miners[miner]["benchmark"] = json.load(open('benchmark-%s.json' % miner))
            print("Reading existing benchmark-%s.json" % miner)
        except:
            print("File benchmark-%s.json does not exist, creating a new one." % miner)
            miners[miner]["benchmark"] = {}

        for pool in pools:
            common_algos = find_common_algos(miners[miner]["supported_algos"], pools[pool]["supported_algos"])
            print("Miner %s and pool %s have %s algos in common" % (miner, pool, len(common_algos.keys())))
            for algo in common_algos.keys():
                if (algo not in miners[miner][
                    "benchmark"].keys() or not skip_existing) and algo not in blacklisted_algos:
                    # Launch bench here
                    pool_params = {"algo": algo,
                                   "wallet": pools[pool]["wallet"],
                                   "password": pools[pool]["password"],
                                   "url": pools[pool]["mine_url"].format(algo=common_algos[algo]),
                                   "port": pools[pool]["results"][common_algos[algo]]["port"]}
                    hashrate = benchmark(miner, algo, pool_params)
                    miners[miner]["benchmark"][algo] = hashrate
                    json.dump(miners[miner]["benchmark"], open("benchmark-%s.json" % miner, 'w'),
                              sort_keys=True, indent=4, separators=(',', ': '))
                    print("Updated benchmark-%s.json !" % miner)

def list_profitability(algo, hashrate, pool):

    mbtc = fetch_mbitcoin_value()
    btc = mbtc * 1000
    revenues = {}
    fields = ['estimate_current', 'estimate_last24h']
    for field in fields:
        revenues[field] = float(pools[pool]["results"][algo][field]) / (float(hashrate) * float(pools[pool]["results"][algo]["mbtc_mh_factor"])) * btc

    fields = ['actual_last24h', 'actual_last24h_shared', 'actual_last24h_solo']
    for field in fields:
        revenues[field] = float(pools[pool]["results"][algo][field]) / (float(hashrate) * float(pools[pool]["results"][algo]["mbtc_mh_factor"])) * mbtc

    return revenues


if __name__ == "__main__":
    populate_supported_algos()
    benchmarked_algos = run_all_benchmarks(True)

    #print (list_profitability("yespowerR16", 1000, "zergpool"))


