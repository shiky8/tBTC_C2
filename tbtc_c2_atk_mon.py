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
# DUST_LIMIT = 600
# FEE = 500
DUST_LIMIT = 546   # Real dust limit in satoshis
FEE = 1000         # slightly higher fee for 3-output tx
MAX_OPRETURN = 80

# ========================
#  UTXOs
# ========================
def get_utxos(address):
    return requests.get(f"{API}/address/{address}/utxo").json()

# ========================
# Balance
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
def send_message(wif, to_address, message):
    key = CBitcoinSecret(wif)
    my_address = str(P2PKHBitcoinAddress.from_pubkey(key.pub))

    balance = get_balance(my_address)
    if balance < (DUST_LIMIT + FEE):
        print("[-] Not enough balance")
        return None

    utxos = get_utxos(my_address)
    if not utxos:
        print("[-] No UTXOs")
        return None

    utxo = utxos[0]

    txid = utxo["txid"]
    vout = utxo["vout"]
    value = utxo["value"]

    send_amount = DUST_LIMIT
    change = value - send_amount - FEE

    msg_data = fit_message(message)

    txin = CMutableTxIn(COutPoint(lx(txid), vout))

    txout = CTxOut(send_amount, P2PKHBitcoinAddress(to_address).to_scriptPubKey())
    op_return = CTxOut(0, CScript([OP_RETURN, msg_data]))

    outputs = [txout, op_return]

    if change > DUST_LIMIT:
        outputs.append(
            CTxOut(change, P2PKHBitcoinAddress(my_address).to_scriptPubKey())
        )

    tx = CMutableTransaction([txin], outputs)

    scriptPubKey = P2PKHBitcoinAddress(my_address).to_scriptPubKey()
    sighash = SignatureHash(scriptPubKey, tx, 0, SIGHASH_ALL)

    sig = key.sign(sighash) + bytes([SIGHASH_ALL])
    tx.vin[0].scriptSig = CScript([sig, key.pub])

    raw_tx = b2x(tx.serialize())

    res = requests.post(f"{API}/tx", data=raw_tx)
    print("[+] TXID:", res.text)

    return res.text

# ========================
# Decode message
# ========================
def decode_message(data):
    try:
        if data.startswith(b"1/2|"):
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

        # keep looping — don't stop on a no-OP_RETURN tx

    return None, None, None

# ========================
# MONITOR
# ========================
def monitor(address, last_tx, mytxid):
    print("[*] Monitoring for messages...")

    while True:
        msg, txid, raw = get_latest_message(address, last_tx)

        # nothing new
        if txid is None:
            time.sleep(5)
            continue

        # skip our own sent tx
        if txid == mytxid:
            last_tx = txid
            time.sleep(5)
            continue

        # new incoming tx with message
        last_tx = txid

        if msg:
            print(f"[NEW] {txid} -> {msg}")
            # break

        time.sleep(5)

# ========================
# MAIN LOOP
# ========================
def menu():
    last_tx ,mytxid= None,None

    wif = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" #atc prive key
    to = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" # targ address
    # addr = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    addr = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" # atc adress

    while True:
        # msg = input("Message: ")

        # mytxid = send_message(wif, to, msg)

        # if mytxid:
            monitor(addr, last_tx, mytxid)
            last_tx = mytxid

if __name__ == "__main__":
    menu()