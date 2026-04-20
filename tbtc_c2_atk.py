import requests
import time
import lzma

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
#  Spent Tracker
# ========================
class SpentTracker:
    def __init__(self):
        self.outpoints = set()      # "txid:vout" strings
        self.pending_utxos = []     # change UTXOs from unconfirmed sends

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
#  Fit message safely
# ========================
def fit_message(message):
    header = b"1/2|"

    compressed = lzma.compress(message.encode())
    if len(compressed) <= MAX_OPRETURN:
        return compressed

    for size in range(len(message), 0, -1):
        part = message[:size]
        comp = lzma.compress(part.encode())

        if len(header) + len(comp) <= MAX_OPRETURN:
            return header + comp

    raise Exception("Message too large")

# ========================
# SEND TX
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

    # ── pick UTXOs until we have enough ──────────────────────────────
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

    # ── build inputs ──────────────────────────────────────────────────
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

    # ── sign each input ───────────────────────────────────────────────
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
        #  mark all selected UTXOs as spent
        for u in selected:
            spent.add(f"{u['txid']}:{u['vout']}")

        #  inject change output as spendable pending UTXO
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
            data = data[4:]
        return lzma.decompress(data).decode("utf-8")
    except Exception as e:
        return f"[decode error] {e}"

# ========================
#  Get latest message
# ========================
def get_latest_message(address, last_seen_tx=None):
    txs = requests.get(f"{API}/address/{address}/txs").json()
    if not txs:
        return None, None, None

    for tx in txs:
        txid = tx["txid"]

        # stop if we hit the last seen tx
        if txid == last_seen_tx:
            return None, None, None

        # skip outgoing (address is sender)
        is_sender = any(
            vin.get("prevout", {}).get("scriptpubkey_address", "") == address
            for vin in tx["vin"]
        )
        if is_sender:
            continue

        # find OP_RETURN in incoming tx
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
#  MONITOR
# ========================
def monitor(address, last_tx, mytxid):
    print("[*] Monitoring for messages...")

    while True:
        msg, txid, raw = get_latest_message(address, last_tx)

        if txid is None:
            time.sleep(5)
            continue

        if txid == mytxid:
            last_tx = txid
            time.sleep(5)
            continue

        last_tx = txid

        if msg:
            print(f"[NEW] {txid} -> {msg}")
            break

        time.sleep(5)

# ========================
#  MAIN LOOP
# ========================
def menu():
    last_tx = None
    spent = SpentTracker()  # persists across sends

    wif  = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"  # atc private key
    to   = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # target address
    addr = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"                    # atc address

    while True:
        msg = input("Message: ")
        mytxid = send_message(wif, to, msg, spent)

        # if mytxid:
        #     monitor(addr, last_tx, mytxid)
        #     last_tx = mytxid

if __name__ == "__main__":
    menu()