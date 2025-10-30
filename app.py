from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Literal, Callable
from datetime import datetime, timezone
import time
import re
import requests

app = FastAPI(title="Crypto backend — balances & history + batch per chain")

# =========================
# CONFIG
# =========================
# !!! ВАЖНО: подставь свой API KEY Tatum ниже
TATUM_API_KEY = "t-..................."

HEADERS_JSON = {"x-api-key": TATUM_API_KEY, "accept": "application/json"}
HEADERS_RPC  = {"x-api-key": TATUM_API_KEY, "content-type": "application/json"}

# RPC Tatum Gateway
ETH_RPC = "https://ethereum-mainnet.gateway.tatum.io"
BSC_RPC = "https://bsc-mainnet.gateway.tatum.io"
SOL_RPC = "https://solana-mainnet.gateway.tatum.io"

# USDT (ETH/BSC/SOL)
USDT = {
    "eth": {
        "contract": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "decimals": 6,
        # keccak256("Transfer(address,address,uint256)")
        "topic_transfer": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
    },
    "bsc": {
        "contract": "0x55d398326f99059fF775485246999027B3197955",
        "decimals": 6,
        "topic_transfer": "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
    },
    "tron": {
        "contract": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
        "decimals": 6,
    },
    "sol": {
        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "decimals": 6,
    },
}

SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

# =========================
# UTILS
# =========================
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def to_wei(x: float, decimals: int = 18) -> int:
    return int(round(x * (10 ** decimals)))

def from_units(x: int, decimals: int) -> float:
    if decimals <= 0:
        return float(x)
    return round(x / (10 ** decimals), 12)

def fmt_decimal(value: float, max_dp: int = 18) -> str:
    s = f"{value:.{max_dp}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
        if "." not in s:
            s = s + ".0"
    return s

# validators
_base58_re = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")
_bech32_re = re.compile(r"^(bc1|tb1|bcrt1)[0-9ac-hj-np-z]+$")
_hex40_re = re.compile(r"^0x[a-fA-F0-9]{40}$")
_tron_re = re.compile(r"^T[a-zA-Z0-9]{33}$")

def is_evm_address(addr: str) -> bool:
    return bool(_hex40_re.fullmatch(addr))

def is_tron_address(addr: str) -> bool:
    return bool(_tron_re.fullmatch(addr))

def is_btc_address(addr: str) -> bool:
    if not addr:
        return False
    if _bech32_re.fullmatch(addr):
        return True
    return _base58_re.fullmatch(addr) is not None and 26 <= len(addr) <= 62

def is_solana_address(addr: str) -> bool:
    if not addr:
        return False
    if not _base58_re.fullmatch(addr):
        return False
    return 32 <= len(addr) <= 44

# HTTP w/ retry
def request_with_retry(
    method: Literal["GET", "POST"],
    url: str,
    headers: Dict[str, str],
    *,
    params: Optional[Dict[str, Any]] = None,
    json: Optional[Dict[str, Any]] = None,
    timeout: int = 20,
    retries: int = 2,
    backoff_factor: float = 0.7,
) -> requests.Response:
    attempt = 0
    while True:
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, params=params, timeout=timeout)
            else:
                r = requests.post(url, headers=headers, params=params, json=json, timeout=timeout)
            if 500 <= r.status_code < 600 and attempt < retries:
                attempt += 1
                time.sleep(backoff_factor * (2 ** (attempt - 1)))
                continue
            return r
        except (requests.Timeout, requests.ConnectionError):
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(backoff_factor * (2 ** (attempt - 1)))

# EVM RPC helpers
def evm_rpc(url: str, method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = request_with_retry("POST", url, HEADERS_RPC, json=payload, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise HTTPException(502, detail=j["error"])
    return j.get("result")

def evm_get_balance(url: str, address: str) -> int:
    res = evm_rpc(url, "eth_getBalance", [address, "latest"])
    return int(res, 16)

def evm_get_logs(url: str, address_contract: str, topic0: str, from_block: str, to_block: str, addr_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    flt: Dict[str, Any] = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": address_contract,
        "topics": [topic0],
    }
    return evm_rpc(url, "eth_getLogs", [flt]) or []

# Solana RPC helpers
def sol_rpc(method: str, params: list) -> Any:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = request_with_retry("POST", SOL_RPC, HEADERS_RPC, json=payload, timeout=25)
    r.raise_for_status()
    j = r.json()
    if "error" in j:
        raise HTTPException(502, detail=j["error"])
    return j.get("result")

def sol_get_signatures_for_address(addr: str, limit: int = 20, before: Optional[str] = None) -> List[Dict[str, Any]]:
    opts: Dict[str, Any] = {"limit": limit}
    if before:
        opts["before"] = before
    return sol_rpc("getSignaturesForAddress", [addr, opts]) or []

def sol_get_transaction(sig: str) -> Dict[str, Any]:
    return sol_rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]) or {}

def sol_get_token_accounts_by_owner(owner: str, mint: str) -> List[str]:
    res = sol_rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    vals = (res or {}).get("value", []) if isinstance(res, dict) else []
    return [v.get("pubkey") for v in vals if isinstance(v, dict) and v.get("pubkey")]

def sol_find_ata(owner: str, mint: str) -> str:
    accs = sol_get_token_accounts_by_owner(owner, mint)
    return accs[0] if accs else ""

# =========================
# MODELS
# =========================
class AddressBody(BaseModel):
    address: str

class AddressesBody(BaseModel):
    addresses: List[str] = Field(..., min_length=1, max_length=100)

class EthHistoryBody(BaseModel):
    address: str
    from_block: Optional[str] = "0x0"
    to_block: Optional[str] = "latest"
    limit_logs: int = Field(2000, ge=1, le=5000)

class EthHistoryBatchBody(BaseModel):
    addresses: List[str] = Field(..., min_length=1, max_length=100)
    from_block: Optional[str] = "0x0"
    to_block: Optional[str] = "latest"
    limit_logs: int = Field(2000, ge=1, le=5000)

class TronHistoryBatchBody(BaseModel):
    addresses: List[str] = Field(..., min_length=1, max_length=100)
    page_size: int = Field(50, ge=1, le=200)
    next_page: Optional[str] = None

class BtcHistoryBatchBody(BaseModel):
    addresses: List[str] = Field(..., min_length=1, max_length=100)
    page_size: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0)

class SolanaHistoryBatchBody(BaseModel):
    addresses: List[str] = Field(..., min_length=1, max_length=100)
    limit: int = Field(20, ge=1, le=100)          
    before: Optional[str] = None                   
    only_token_transfers: bool = False             
    only_usdt: bool = False                        

class NativeBalance(BaseModel):
    chain: Literal["btc", "eth", "bsc", "tron", "sol"]
    value: str
    raw: Optional[Any] = None

class FungibleToken(BaseModel):
    chain: Literal["eth", "bsc", "tron", "sol"]
    contract_or_mint: str
    symbol: Optional[str] = None
    decimals: Optional[int] = None
    amount: Optional[str] = None

class BalanceResponse(BaseModel):
    status: Literal["ok", "error"]
    address: str
    native: Optional[NativeBalance] = None
    tokens: Optional[List[FungibleToken]] = None
    error_detail: Optional[str] = None
    timestamp: str

# =========================
# BALANCES (batch)
# =========================
def _balance_eth_one(address: str) -> BalanceResponse:
    if not is_evm_address(address):
        return BalanceResponse(status="error", address=address, error_detail="Invalid ETH address", timestamp=utc_now())
    try:
        wei = evm_get_balance(ETH_RPC, address)
        return BalanceResponse(
            status="ok",
            address=address,
            native=NativeBalance(chain="eth", value=fmt_decimal(from_units(wei, 18))),
            timestamp=utc_now(),
        )
    except requests.RequestException as e:
        return BalanceResponse(status="error", address=address, error_detail=f"ETH RPC error: {e}", timestamp=utc_now())

def _balance_bsc_one(address: str) -> BalanceResponse:
    if not is_evm_address(address):
        return BalanceResponse(status="error", address=address, error_detail="Invalid BSC address", timestamp=utc_now())
    try:
        wei = evm_get_balance(BSC_RPC, address)
        return BalanceResponse(
            status="ok",
            address=address,
            native=NativeBalance(chain="bsc", value=fmt_decimal(from_units(wei, 18))),
            timestamp=utc_now(),
        )
    except requests.RequestException as e:
        return BalanceResponse(status="error", address=address, error_detail=f"BSC RPC error: {e}", timestamp=utc_now())

def _balance_tron_one(address: str) -> BalanceResponse:
    if not is_tron_address(address):
        return BalanceResponse(status="error", address=address, error_detail="Invalid TRON address", timestamp=utc_now())
    try:
        url = f"https://api.tatum.io/v3/tron/account/{address}"
        r = request_with_retry("GET", url, HEADERS_JSON, timeout=20)
        r.raise_for_status()
        j = r.json()
        bal = 0.0
        try:
            data = j.get("data") or {}
            bal = float(data.get("balance", 0)) if isinstance(data, dict) else float(j.get("balance", 0))
        except Exception:
            bal = float(j.get("balance", 0) or 0)
        return BalanceResponse(
            status="ok",
            address=address,
            native=NativeBalance(chain="tron", value=fmt_decimal(bal)),
            timestamp=utc_now(),
        )
    except requests.RequestException as e:
        return BalanceResponse(status="error", address=address, error_detail=f"TRON API error: {e}", timestamp=utc_now())

def _balance_btc_one(address: str) -> BalanceResponse:
    if not is_btc_address(address):
        return BalanceResponse(status="error", address=address, error_detail="Invalid BTC address", timestamp=utc_now())
    try:
        url = f"https://api.tatum.io/v3/bitcoin/address/balance/{address}"
        r = request_with_retry("GET", url, HEADERS_JSON, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        bal = float(j.get("incoming", 0)) - float(j.get("outgoing", 0))
        return BalanceResponse(
            status="ok",
            address=address,
            native=NativeBalance(chain="btc", value=fmt_decimal(bal)),
            raw=j,
            timestamp=utc_now(),
        )
    except requests.RequestException as e:
        return BalanceResponse(status="error", address=address, error_detail=f"BTC API error: {e}", timestamp=utc_now())

def _balance_solana_one(address: str) -> BalanceResponse:
    if not is_solana_address(address):
        return BalanceResponse(status="error", address=address, error_detail="Invalid Solana address", timestamp=utc_now())
    try:
        url = f"https://api.tatum.io/v3/solana/account/balance/{address}"
        r = request_with_retry("GET", url, HEADERS_JSON, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        bal = float(j.get("balance", 0)) if isinstance(j, dict) else 0.0
        return BalanceResponse(
            status="ok",
            address=address,
            native=NativeBalance(chain="sol", value=fmt_decimal(bal)),
            timestamp=utc_now(),
        )
    except requests.RequestException as e:
        return BalanceResponse(status="error", address=address, error_detail=f"SOL API error: {e}", timestamp=utc_now())

def _run_batch(addresses: List[str], fn: Callable[[str], BalanceResponse]) -> Dict[str, Any]:
    results: List[BalanceResponse] = []
    for a in addresses:
        results.append(fn(a))
    return {"status": "ok", "count": len(results), "results": [r.dict() for r in results], "timestamp": utc_now()}

@app.post("/eth/balance_batch")
def eth_balance_batch(body: AddressesBody):
    return _run_batch(body.addresses, _balance_eth_one)

@app.post("/bsc/balance_batch")
def bsc_balance_batch(body: AddressesBody):
    return _run_batch(body.addresses, _balance_bsc_one)

@app.post("/tron/balance_batch")
def tron_balance_batch(body: AddressesBody):
    return _run_batch(body.addresses, _balance_tron_one)

@app.post("/btc/balance_batch")
def btc_balance_batch(body: AddressesBody):
    return _run_batch(body.addresses, _balance_btc_one)

@app.post("/solana/balance_batch")
def solana_balance_batch(body: AddressesBody):
    return _run_batch(body.addresses, _balance_solana_one)

# =========================
# HISTORIES
# =========================
def _evm_history_usdt(url_rpc: str, chain_key: Literal["eth", "bsc"], address: str, from_block: str, to_block: str, limit_logs: int) -> Dict[str, Any]:
    if not is_evm_address(address):
        return {"status": "error", "address": address, "error_detail": f"Invalid {chain_key.upper()} address", "timestamp": utc_now()}
    try:
        logs = evm_get_logs(
            url_rpc,
            USDT[chain_key]["contract"],
            USDT[chain_key]["topic_transfer"],
            from_block,
            to_block,
        )
        if len(logs) > limit_logs:
            logs = logs[-limit_logs:]
        out = []
        for L in logs:
            out.append({
                "blockNumber": L.get("blockNumber"),
                "txHash": L.get("transactionHash"),
                "logIndex": L.get("logIndex"),
                "data": L.get("data"),
                "topics": L.get("topics"),
                "address": L.get("address"),
            })
        return {"status": "ok", "address": address, "count": len(out), "results": out, "timestamp": utc_now()}
    except requests.RequestException as e:
        return {"status": "error", "address": address, "error_detail": f"{chain_key.upper()} RPC error: {e}", "timestamp": utc_now()}

@app.post("/eth/history_usdt")
def eth_history_usdt(body: EthHistoryBody):
    return _evm_history_usdt(ETH_RPC, "eth", body.address, body.from_block, body.to_block, body.limit_logs)

@app.post("/bsc/history_usdt")
def bsc_history_usdt(body: EthHistoryBody):
    return _evm_history_usdt(BSC_RPC, "bsc", body.address, body.from_block, body.to_block, body.limit_logs)

@app.post("/eth/history_usdt_batch")
def eth_history_usdt_batch(body: EthHistoryBatchBody):
    res = []
    for a in body.addresses:
        res.append(_evm_history_usdt(ETH_RPC, "eth", a, body.from_block, body.to_block, body.limit_logs))
    return {"status": "ok", "count": len(res), "results": res, "timestamp": utc_now()}

@app.post("/bsc/history_usdt_batch")
def bsc_history_usdt_batch(body: EthHistoryBatchBody):
    res = []
    for a in body.addresses:
        res.append(_evm_history_usdt(BSC_RPC, "bsc", a, body.from_block, body.to_block, body.limit_logs))
    return {"status": "ok", "count": len(res), "results": res, "timestamp": utc_now()}
def _tron_history_one(address: str, page_size: int, next_page: Optional[str]) -> Dict[str, Any]:
    if not is_tron_address(address):
        return {"status": "error", "address": address, "error_detail": "Invalid TRON address", "timestamp": utc_now()}
    url = f"https://api.tatum.io/v3/tron/transaction/account/{address}"
    params = {"pageSize": page_size}
    if next_page:
        params["next"] = next_page
    try:
        r = request_with_retry("GET", url, HEADERS_JSON, params=params, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        return {"status": "ok", "address": address, "count": len(j.get("data", [])), "results": j.get("data", []), "next": j.get("next"), "timestamp": utc_now()}
    except requests.RequestException as e:
        return {"status": "error", "address": address, "error_detail": f"TRON API error: {e}", "timestamp": utc_now()}

def _tron_history_usdt_one(address: str, page_size: int, next_page: Optional[str]) -> Dict[str, Any]:
    if not is_tron_address(address):
        return {"status": "error", "address": address, "error_detail": "Invalid TRON address", "timestamp": utc_now()}
    url = f"https://api.tatum.io/v3/tron/transaction/account/{address}/trc20"
    params = {"pageSize": page_size}
    if next_page:
        params["next"] = next_page
    try:
        r = request_with_retry("GET", url, HEADERS_JSON, params=params, timeout=20)
        r.raise_for_status()
        j = r.json() or {}
        items = [it for it in (j.get("data", []) or []) if it.get("token") == USDT["tron"]["contract"]]
        return {"status": "ok", "address": address, "count": len(items), "results": items, "next": j.get("next"), "timestamp": utc_now()}
    except requests.RequestException as e:
        return {"status": "error", "address": address, "error_detail": f"TRON API error: {e}", "timestamp": utc_now()}

@app.post("/tron/history")
def tron_history(body: TronHistoryBatchBody):
    return _tron_history_one(body.addresses[0], body.page_size, body.next_page)

@app.post("/tron/history_usdt")
def tron_history_usdt(body: TronHistoryBatchBody):
    return _tron_history_usdt_one(body.addresses[0], body.page_size, body.next_page)

@app.post("/tron/history_batch")
def tron_history_batch(body: TronHistoryBatchBody):
    out = []
    for a in body.addresses:
        out.append(_tron_history_one(a, body.page_size, body.next_page))
    return {"status": "ok", "count": len(out), "results": out, "timestamp": utc_now()}

@app.post("/tron/history_usdt_batch")
def tron_history_usdt_batch(body: TronHistoryBatchBody):
    out = []
    for a in body.addresses:
        out.append(_tron_history_usdt_one(a, body.page_size, body.next_page))
    return {"status": "ok", "count": len(out), "results": out, "timestamp": utc_now()}
def _btc_history_one(address: str, page_size: int, offset: int) -> Dict[str, Any]:
    if not is_btc_address(address):
        return {"status": "error", "address": address, "error_detail": "Invalid BTC address", "timestamp": utc_now()}
    url = f"https://api.tatum.io/v3/bitcoin/transaction/address/{address}"
    params = {"pageSize": page_size, "offset": offset}
    try:
        r = request_with_retry("GET", url, HEADERS_JSON, params=params, timeout=20)
        r.raise_for_status()
        j = r.json() or []
        return {"status": "ok", "address": address, "count": len(j), "results": j, "timestamp": utc_now()}
    except requests.RequestException as e:
        return {"status": "error", "address": address, "error_detail": f"BTC API error: {e}", "timestamp": utc_now()}

@app.post("/btc/history")
def btc_history(body: BtcHistoryBatchBody):
    return _btc_history_one(body.addresses[0], body.page_size, body.offset)

@app.post("/btc/history_batch")
def btc_history_batch(body: BtcHistoryBatchBody):
    out = []
    for a in body.addresses:
        out.append(_btc_history_one(a, body.page_size, body.offset))
    return {"status": "ok", "count": len(out), "results": out, "timestamp": utc_now()}
    
@app.post("/solana/history_batch")
def solana_history_batch(body: SolanaHistoryBatchBody):
    results = []
    for addr in body.addresses:
        if not is_solana_address(addr):
            results.append({"status": "error", "address": addr, "error_detail": "Invalid Solana address", "timestamp": utc_now()})
            continue
        query_address = addr
        if body.only_usdt:
            ata = sol_find_ata(addr, USDT["sol"]["mint"])
            if ata:
                query_address = ata

        try:
            sigs = sol_get_signatures_for_address(query_address, limit=body.limit, before=body.before)
            out_txs = []
            for s in sigs:
                sig = s.get("signature")
                if not sig:
                    continue
                tx = sol_get_transaction(sig) or {}
                if body.only_token_transfers:
                    instr = (((tx.get("transaction") or {}).get("message") or {}).get("instructions") or [])
                    has_spl = False
                    for i in instr:
                        if isinstance(i, dict):
                            pid = i.get("programId") or i.get("programIdIndex")
                            if i.get("program") == "spl-token" or pid == SPL_TOKEN_PROGRAM:
                                has_spl = True
                                break
                    if not has_spl:
                        continue
                out_txs.append({
                    "signature": sig,
                    "slot": s.get("slot"),
                    "blockTime": s.get("blockTime"),
                    "tx": tx,
                })

            results.append({
                "status": "ok",
                "address": addr,
                "count": len(out_txs),
                "results": out_txs,
                "timestamp": utc_now(),
                "query_address": query_address,
                "before": body.before,
            })
        except requests.RequestException as e:
            results.append({"status": "error", "address": addr, "error_detail": f"SOL RPC error: {e}", "timestamp": utc_now()})

    return {"status": "ok", "count": len(results), "results": results, "timestamp": utc_now()}

# =========================
# HEALTH
# =========================
@app.get("/test")
def test():
    return {"alive": True, "provider": "tatum+rpc", "timestamp": utc_now()}

# =========================
# RUN
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
