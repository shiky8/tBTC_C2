import os
import hashlib
import ecdsa
import base58
from Crypto.Hash import RIPEMD160

# ========================
#  Generate Private Key
# ========================
def generate_private_key():
    return os.urandom(32).hex()

# ========================
# Private -> Public Key
# ========================
def private_to_public(privkey_hex):
    sk = ecdsa.SigningKey.from_string(
        bytes.fromhex(privkey_hex),
        curve=ecdsa.SECP256k1
    )
    vk = sk.verifying_key
    return b'\x04' + vk.to_string()

# ========================
#  Public -> Address (Testnet)
# ========================
def public_to_address(pubkey):
    sha = hashlib.sha256(pubkey).digest()

    #  FIXED RIPEMD160
    h = RIPEMD160.new()
    h.update(sha)
    ripe = h.digest()

    # testnet prefix
    prefix = b'\x6f' + ripe

    checksum = hashlib.sha256(hashlib.sha256(prefix).digest()).digest()[:4]

    return base58.b58encode(prefix + checksum).decode()

# ========================
#  Private -> WIF
# ========================
def private_to_wif(privkey_hex):
    extended = b'\xef' + bytes.fromhex(privkey_hex)  # testnet prefix
    checksum = hashlib.sha256(hashlib.sha256(extended).digest()).digest()[:4]
    return base58.b58encode(extended + checksum).decode()

# ========================
# Generate Wallet
# ========================
def create_wallet():
    priv = generate_private_key()
    pub = private_to_public(priv)
    addr = public_to_address(pub)
    wif = private_to_wif(priv)

    print("\n===== TESTNET WALLET (tBTC) =====")
    print("Private Key (HEX):", priv)
    print("Private Key (WIF):", wif)
    print("Public Key:", pub.hex())
    print("Address:", addr)
    print("=================================\n")

    return addr

# ========================
# Faucet Helper
# ========================
def show_faucets(address):
    print("[*] Get FREE tBTC from faucets:\n")

    print("1. https://coinfaucet.eu/en/btc-testnet/")
    print("2. https://tbtc.bitaps.com/")
    print("3. https://bitcoinfaucet.uo1.net/")

    print("\n[+] Paste your address:")
    print("   ", address)

# ========================
# MAIN
# ========================
if __name__ == "__main__":
    addr = create_wallet()
    show_faucets(addr)
