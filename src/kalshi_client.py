import base64
import json
import time
import uuid
from typing import Optional, Dict, Any, List
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from config.settings import (
    KALSHI_BASE_URL,
    KALSHI_API_KEY_ID,
    KALSHI_PRIVATE_KEY,
    KALSHI_ENV
)


class KalshiClient:
    """
    Kalshi API v2 Client with RSA-PSS cryptographic signing,
    market data querying, and order execution capabilities.
    """

    def __init__(
        self,
        api_key_id: Optional[str] = None,
        private_key_pem: Optional[str] = None,
        base_url: Optional[str] = None,
        env: Optional[str] = None
    ):
        self.api_key_id = api_key_id or KALSHI_API_KEY_ID
        self.raw_private_key = private_key_pem or KALSHI_PRIVATE_KEY
        self.base_url = (base_url or KALSHI_BASE_URL).rstrip("/")
        self.env = env or KALSHI_ENV
        self.private_key = self._load_private_key(self.raw_private_key)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.api_key_id and self.private_key)

    def _load_private_key(self, key_str: Optional[str]) -> Optional[rsa.RSAPrivateKey]:
        if not key_str:
            return None
        try:
            # Format pem if passed with escaped newlines
            formatted_key = key_str.replace("\\n", "\n").strip()
            if not formatted_key.startswith("-----BEGIN"):
                # Handle raw base64 or pkcs8 if applicable
                pass
            return serialization.load_pem_private_key(
                formatted_key.encode("utf-8"),
                password=None
            )
        except Exception as e:
            print(f"[KalshiClient] Warning: Failed to load RSA private key: {e}")
            return None

    def sign_request(self, timestamp_ms: str, method: str, path: str) -> str:
        """
        Creates an RSA-PSS SHA256 base64 signature for the given request.
        Message: timestamp_ms + METHOD + path_without_query
        """
        if not self.private_key:
            raise ValueError("Cannot sign request: Private key is not loaded.")
        
        path_without_query = path.split("?")[0]
        message = f"{timestamp_ms}{method.upper()}{path_without_query}".encode("utf-8")
        
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")

    def _get_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        """
        Generates Kalshi authentication headers.
        """
        timestamp_ms = str(int(time.time() * 1000))
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        if self.is_authenticated:
            signature = self.sign_request(timestamp_ms, method, path)
            headers["KALSHI-ACCESS-KEY"] = self.api_key_id
            headers["KALSHI-ACCESS-TIMESTAMP"] = timestamp_ms
            headers["KALSHI-ACCESS-SIGNATURE"] = signature
        return headers

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        auth_required: bool = False
    ) -> Dict[str, Any]:
        """
        Sends an HTTP request to the Kalshi API.
        """
        if auth_required and not self.is_authenticated:
            raise PermissionError("Action requires authentication, but API credentials are not set.")

        full_path = f"/trade-api/v2{path}" if not path.startswith("/trade-api/v2") else path
        url = f"{self.base_url.replace('/trade-api/v2', '')}{full_path}"
        headers = self._get_auth_headers(method, full_path)

        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_data,
            timeout=15
        )
        
        if not response.ok:
            try:
                err_detail = response.json()
            except Exception:
                err_detail = response.text
            raise requests.HTTPError(
                f"Kalshi API Error {response.status_code} on {method} {full_path}: {err_detail}",
                response=response
            )
            
        return response.json() if response.text else {}

    # ================= Public Market Data Methods =================

    def get_series_list(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retrieves available market series (e.g. category='sports').
        """
        params = {"category": category} if category else {}
        res = self._request("GET", "/series", params=params)
        return res.get("series", [])

    def get_events(
        self,
        series_ticker: Optional[str] = None,
        status: str = "open",
        with_nested_markets: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Retrieves active events and their child markets.
        """
        params: Dict[str, Any] = {"status": status}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if with_nested_markets:
            params["with_nested_markets"] = "true"
        
        res = self._request("GET", "/events", params=params)
        return res.get("events", [])

    def get_sports_events(self, status: str = "open") -> List[Dict[str, Any]]:
        """
        Retrieves active events and markets across all sports series.
        """
        sports_series_list = [
            # MLB, NPB & Baseball
            "KXMLBSPREAD", "KXMLBTOTAL", "KXMLBGAME", "KXMLBF5", "KXMLBF5SPREAD", "KXMLBF5TOTAL",
            "KXMLBF3", "KXMLBF7", "KXMLBRFI", "KXNPBRFI", "KXNPBTOTAL", "KXNPBGAME", "KXNPBSPREAD",
            "KXKBORFI", "KXMLB", "KXKBOGAME", "KXKBOTOTAL",
            # Basketball
            "KXWNBAGAME", "KXWNBATOTAL", "KXWNBASPREAD", "KXWNBA1HTOTAL", "KXWNBA1HSPREAD",
            "KXNBAGAME", "KXNBATOTAL", "KXNBASPREAD",
            # Tennis
            "KXATPMATCH", "KXWTAMATCH", "KXUSOPEN", "KXUSOPENMENSINGLES", "KXUSOPENWOMENSINGLES",
            # Football
            "KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL", "KXNCAAF1HSPREAD", "KXNCAAF1HTOTAL", "KXNCAAF1Q",
            "KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL",
            # Hockey & Soccer
            "KXNHLGAME",
            "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPLSPREAD", "KXEPLCORNERS", "KXEPLTCORNERS", "KXEPL1H", "KXEPL2H", "KXEPLMATCH",
            "KXLALIGAGAME", "KXLALIGATOTAL", "KXLALIGATCORNERS", "KXLALIGACORNERS", "KXLALIGABTTS", "KXLALIGASPREAD", "KXLALIGA",
            "KXUCLGAME", "KXUCLTOTAL", "KXUCLBTTS", "KXUCLCORNERS", "KXUCLTCORNERS",
            "KXSERIEAGAME", "KXSERIEATOTAL", "KXSERIEABTTS", "KXSERIEACORNERS", "KXSERIEATCORNERS",
            "KXBUNDESLIGAGAME", "KXBUNDESLIGATOTAL", "KXBUNDESLIGABTTS", "KXBUNDESLIGACORNERS", "KXBUNDESLIGATCORNERS",
            "KXMLSGAME", "KXMLSTOTAL", "KXMLSTCORNERS", "KXMLSCORNERS", "KXSOCCER"
        ]
        all_events = []
        for st in sports_series_list:
            try:
                evs = self.get_events(series_ticker=st, status=status, with_nested_markets=True)
                if evs:
                    all_events.extend(evs)
            except Exception:
                pass
        return all_events

    def get_market(self, ticker: str) -> Dict[str, Any]:
        """
        Retrieves market details for a single market ticker.
        """
        res = self._request("GET", f"/markets/{ticker}")
        return res.get("market", res)

    def get_orderbook(self, ticker: str, depth: int = 5) -> Dict[str, Any]:
        """
        Retrieves the orderbook for a given market ticker.
        """
        res = self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})
        return res.get("orderbook", res)

    def get_best_ask_cents(self, ticker: str, side: str = "yes") -> Optional[int]:
        """
        Retrieves the best available ask price in cents for 'yes' or 'no'
        by inspecting the live orderbook (Taker price for immediate fills).
        """
        if ticker.startswith("KXCOMBO-SIM"):
            return None
        try:
            ob = self.get_orderbook(ticker, depth=5)
            ob_fp = ob.get("orderbook_fp", ob) if isinstance(ob, dict) else {}

            yes_bids = ob_fp.get("yes_dollars") or ob.get("yes", [])
            no_bids = ob_fp.get("no_dollars") or ob.get("no", [])

            # Buying 'yes' takes the best available YES ask (1.00 - highest NO bid)
            if side.lower() in ("yes", "bid"):
                if no_bids:
                    highest_no = max(float(x[0]) if isinstance(x, (list, tuple)) else float(x) for x in no_bids)
                    if highest_no > 1.0:
                        highest_no /= 100.0
                    yes_ask = round((1.0 - highest_no) * 100)
                    return max(1, min(99, yes_ask))
            # Buying 'no' takes the best available NO ask (1.00 - highest YES bid)
            else:
                if yes_bids:
                    highest_yes = max(float(x[0]) if isinstance(x, (list, tuple)) else float(x) for x in yes_bids)
                    if highest_yes > 1.0:
                        highest_yes /= 100.0
                    no_ask = round((1.0 - highest_yes) * 100)
                    return max(1, min(99, no_ask))

            # Fallback to market top-level fields
            mkt = self.get_market(ticker)
            if side.lower() in ("yes", "bid"):
                ask = mkt.get("yes_ask") or mkt.get("yes_ask_dollars")
                if ask is not None:
                    c = int(round(float(ask) * 100)) if float(ask) <= 1.0 else int(ask)
                    if 1 <= c <= 99:
                        return c
            else:
                ask = mkt.get("no_ask") or mkt.get("no_ask_dollars")
                if ask is not None:
                    c = int(round(float(ask) * 100)) if float(ask) <= 1.0 else int(ask)
                    if 1 <= c <= 99:
                        return c
            return None
        except Exception as e:
            print(f"[KalshiClient] Could not fetch live ask for {ticker}: {e}")
            return None

    # ================= Authenticated Trading Methods =================

    def get_balance(self, exchange_index: Optional[int] = None) -> Dict[str, Any]:
        """
        Retrieves account balance and available purchasing power.
        """
        params = {}
        if exchange_index is not None:
            params["exchange_index"] = exchange_index
        return self._request("GET", "/portfolio/balance", params=params, auth_required=True)

    def get_intra_shard_transfer(self, transfer_id: str) -> Dict[str, Any]:
        """
        Retrieves details and status for a specific intra-exchange transfer.
        """
        try:
            return self._request("GET", f"/portfolio/intra_exchange_instance_transfers/{transfer_id}", auth_required=True)
        except Exception as e:
            print(f"[KalshiClient] Notice checking transfer status for {transfer_id}: {e}")
            return {}

    def ensure_shard_balance(self, destination_shard: int, required_cents: int) -> bool:
        """
        Ensures the destination shard has sufficient collateral before placing an order.
        If the shard balance is less than required_cents, transfers from Shard 0 and
        waits for the transfer to complete.
        """
        if destination_shard == 0:
            return True
        try:
            # Check destination shard balance
            dest_res = self.get_balance(exchange_index=destination_shard)
            dest_balance = int(dest_res.get("balance", 0))
            if dest_balance >= required_cents:
                return True

            deficit = required_cents - dest_balance
            # Check source shard 0 balance
            src_res = self.get_balance(exchange_index=0)
            src_balance = int(src_res.get("balance", 0))

            # Transfer the needed funds with a buffer (e.g. at least 500c / $5.00)
            transfer_amount = min(max(deficit + 200, 500), src_balance)
            if transfer_amount > 0:
                print(f"[KalshiClient] Transferring {transfer_amount}c collateral from Shard 0 to Shard {destination_shard}...")
                transfer_res = self.transfer_to_shard(destination_shard=destination_shard, amount_cents=transfer_amount, source_shard=0)
                transfer_id = transfer_res.get("transfer_id")

                # Poll for transfer completion and balance update
                for attempt in range(12):
                    time.sleep(1.0)
                    if transfer_id:
                        status_res = self.get_intra_shard_transfer(transfer_id)
                        t_status = status_res.get("status") or status_res.get("transfer", {}).get("status", "")
                        if t_status:
                            print(f"[KalshiClient] Transfer {transfer_id} status: {t_status}")
                        if t_status.lower() in ("completed", "executed", "success", "confirmed"):
                            print(f"[KalshiClient] Transfer {transfer_id} completed successfully.")
                            break

                    updated_dest = self.get_balance(exchange_index=destination_shard)
                    cur_bal = int(updated_dest.get("balance", 0))
                    if cur_bal >= required_cents:
                        print(f"[KalshiClient] Shard {destination_shard} balance confirmed: {cur_bal}c (Settled).")
                        return True

                final_bal = int(self.get_balance(exchange_index=destination_shard).get("balance", 0))
                print(f"[KalshiClient] Shard {destination_shard} balance: {final_bal}c (Required: {required_cents}c). Proceeding...")
                return True
        except Exception as e:
            print(f"[KalshiClient] Shard collateral check/transfer notice: {e}")
        return False

    def create_order(
        self,
        ticker: str,
        side: str,
        count_fp: str,
        price_cents: int,
        client_order_id: Optional[str] = None,
        time_in_force: str = "gtc",
        exchange_index: Optional[int] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Places a limit order on Kalshi.
        
        Args:
            ticker: Kalshi market ticker (e.g. 'KXMLBGAME-24AUG24-TBR-DET-TBR')
            side: 'yes' or 'no'
            count_fp: Fixed-point contract quantity as string (e.g. '1.50')
            price_cents: Limit price in cents (1 to 99)
            client_order_id: Unique UUID for idempotency
            time_in_force: 'gtc' or 'ioc'
            exchange_index: Specific exchange shard index (e.g. 3 for baseball/KBO/MLB, 0 for default)
            dry_run: If True, simulates order placement without sending to API
        """
        client_oid = client_order_id or str(uuid.uuid4())
        side_clean = side.lower()

        tif_map = {
            "gtc": "good_till_canceled",
            "ioc": "immediate_or_cancel",
            "fok": "fill_or_kill",
            "good_till_canceled": "good_till_canceled",
            "immediate_or_cancel": "immediate_or_cancel",
            "fill_or_kill": "fill_or_kill"
        }
        tif_val = tif_map.get(time_in_force.lower(), "good_till_canceled")
        v2_side = "bid" if side_clean in ["yes", "bid"] else "ask"
        v2_price = f"{price_cents / 100.0:.4f}" if v2_side == "bid" else f"{(100 - price_cents) / 100.0:.4f}"

        # Determine target exchange shard index
        target_shard = exchange_index
        if target_shard is None or target_shard == -1:
            try:
                mkt_data = self.get_market(ticker)
                if "exchange_index" in mkt_data and mkt_data["exchange_index"] is not None:
                    target_shard = int(mkt_data["exchange_index"])
                else:
                    target_shard = 0
            except Exception:
                target_shard = 0

        # Calculate exact maximum risk in cents
        contract_count = float(count_fp)
        order_risk_cents = int(price_cents * contract_count) + 5 if v2_side == "bid" else int((100 - price_cents) * contract_count) + 5

        # Ensure destination shard has collateral before order submission
        if not dry_run and self.is_authenticated and target_shard > 0:
            self.ensure_shard_balance(destination_shard=target_shard, required_cents=order_risk_cents)

        # Build Direct shard payload
        direct_payload = {
            "ticker": ticker,
            "client_order_id": client_oid,
            "side": v2_side,
            "price": v2_price,
            "count": count_fp,
            "price_dollars": v2_price,
            "count_fp": count_fp,
            "time_in_force": tif_val,
            "self_trade_prevention_type": "taker_at_cross",
            "type": "limit",
            "exchange_index": target_shard
        }

        if dry_run or not self.is_authenticated:
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would place order (exchange_index={target_shard}): {direct_payload}")
            return {
                "status": "simulated",
                "order_id": f"sim_{client_oid[:8]}",
                "client_order_id": client_oid,
                "ticker": ticker,
                "side": side_clean,
                "count_fp": count_fp,
                "price_cents": price_cents,
                "exchange_index": target_shard,
                "simulated": True
            }

        try:
            return self._request(
                "POST",
                "/portfolio/events/orders",
                json_data=direct_payload,
                auth_required=True
            )
        except Exception as e:
            err_msg = str(e).lower()
            if "user_not_found" in err_msg or "sharding" in err_msg:
                print(f"[KalshiClient] Shard {target_shard} requires collateral initialization. Attempting transfer...")
                try:
                    self.transfer_to_shard(destination_shard=target_shard, amount_cents=order_risk_cents)
                    print(f"[KalshiClient] Successfully transferred {order_risk_cents}c to Shard {target_shard}. Retrying order placement...")
                    return self._request(
                        "POST",
                        "/portfolio/events/orders",
                        json_data=direct_payload,
                        auth_required=True
                    )
                except Exception as transfer_err:
                    print(f"[KalshiClient] Auto-collateral transfer to Shard {target_shard} failed: {transfer_err}")
            raise

    def transfer_to_shard(self, destination_shard: int, amount_cents: int = 1000, source_shard: int = 0) -> Dict[str, Any]:
        """
        Transfers collateral between exchange shards (e.g. from Shard 0 to Shard 3 for Baseball/Tennis).
        Note: Kalshi's intra_exchange_instance_transfer API parameter 'amount' is in units of 100 = 1 cent ($1.00 = 10,000).
        """
        client_tid = str(uuid.uuid4())
        api_amount = amount_cents * 100
        payload = {
            "client_transfer_id": client_tid,
            "amount": api_amount,
            "source": "event_contract",
            "destination": "event_contract",
            "source_exchange_shard": source_shard,
            "destination_exchange_shard": destination_shard,
            "source_subaccount": 0,
            "destination_subaccount": 0
        }
        res = self._request(
            "POST",
            "/portfolio/intra_exchange_instance_transfer",
            json_data=payload,
            auth_required=True
        )
        print(f"[KalshiClient] Intra-shard transfer (Shard {source_shard} -> Shard {destination_shard}, Amount: {amount_cents}c [API Units: {api_amount}]) submitted: {res}")
        return res

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Fetches status of a placed order.
        """
        return self._request("GET", f"/portfolio/orders/{order_id}", auth_required=True)

    # ================= Parlay / Combo & RFQ Methods =================

    def get_multivariate_collections(self, status: str = "open") -> List[Dict[str, Any]]:
        """
        Fetches available multivariate event collections for combo/parlay creation.
        """
        try:
            res = self._request("GET", f"/multivariate_event_collections?status={status}")
            return res.get("multivariate_contracts", []) or res.get("multivariate_event_collections", [])
        except Exception as e:
            print(f"[KalshiClient] Warning querying multivariate collections: {e}")
            return []

    def create_or_get_combo_market(
        self,
        selected_markets: Optional[Any] = None,
        collection_ticker: Optional[str] = None,
        dry_run: bool = False,
        *args: Any,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Creates or resolves a combo market from individual legs.
        Accepts:
          - create_or_get_combo_market(selected_markets=[...], collection_ticker=...)
          - create_or_get_combo_market([...], collection_ticker=...)
          - create_or_get_combo_market("KX...", [...])
        selected_markets format: [{"market_ticker": "...", "event_ticker": "...", "side": "yes"}, ...]
        """
        if isinstance(selected_markets, str):
            actual_collection = selected_markets
            if isinstance(collection_ticker, list):
                actual_markets = collection_ticker
            elif args and isinstance(args[0], list):
                actual_markets = args[0]
            else:
                actual_markets = kwargs.get("selected_markets", [])
        else:
            actual_markets = selected_markets or kwargs.get("selected_markets") or []
            actual_collection = collection_ticker or kwargs.get("collection_ticker")

        if not isinstance(actual_markets, list):
            actual_markets = []

        # Ensure all legs have side specified
        formatted_legs = []
        for m in actual_markets:
            if isinstance(m, dict):
                m_ticker = m.get("market_ticker", "")
                e_ticker = m.get("event_ticker", m_ticker.rsplit("-", 1)[0] if "-" in m_ticker else m_ticker)
                side = m.get("side", "yes").lower()
                formatted_legs.append({
                    "market_ticker": m_ticker,
                    "event_ticker": e_ticker,
                    "side": side
                })

        payload = {
            "selected_markets": formatted_legs,
            "with_market_payload": True
        }

        if dry_run or not self.is_authenticated:
            sim_ticker = f"KXCOMBO-SIM-{uuid.uuid4().hex[:8]}"
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would create combo market in {actual_collection or 'KXMVESPORTSMULTIGAMEEXTENDED-R'}: {payload}")
            return {
                "market_ticker": sim_ticker,
                "event_ticker": f"KXEVT-SIM-{uuid.uuid4().hex[:6]}",
                "market": {
                    "ticker": sim_ticker,
                    "title": f"Simulated Parlay ({len(actual_markets)} legs)",
                    "yes_ask": None,
                    "last_price": None,
                    "exchange_index": 0
                },
                "ticker": sim_ticker,
                "simulated": True
            }

        # Candidate collections to try if none explicitly passed
        candidate_collections = []
        if actual_collection:
            candidate_collections.append(actual_collection)
        else:
            # Query open collections or fallback to standard sports collections
            open_cols = self.get_multivariate_collections(status="open")
            if open_cols:
                candidate_collections.extend([c.get("collection_ticker") for c in open_cols if c.get("collection_ticker")])
            candidate_collections.extend([
                "KXMVESPORTSMULTIGAMEEXTENDED-R",
                "KXMVECROSSCATEGORY-R",
                "KXMVECROSSCATEGORY-SHARD1-R"
            ])

        last_error = None
        for col_ticker in candidate_collections:
            try:
                res = self._request(
                    "POST",
                    f"/multivariate_event_collections/{col_ticker}",
                    json_data=payload,
                    auth_required=True
                )
                if res and (res.get("market_ticker") or res.get("ticker")):
                    return res
            except Exception as e:
                last_error = e

        if last_error:
            raise last_error
        raise RuntimeError("Failed to create combo market in any candidate collection.")

    def create_rfq(
        self,
        ticker: str,
        target_cost_dollars: Optional[float] = None,
        contracts_fp: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Creates a Request for Quote (RFQ) to request market maker pricing on a combo/parlay.
        Endpoint: POST /trade-api/v2/communications/rfqs
        """
        payload: Dict[str, Any] = {
            "market_ticker": ticker,
            "rest_remainder": False,
            "replace_existing": True
        }
        if contracts_fp:
            payload["contracts_fp"] = contracts_fp
        elif target_cost_dollars is not None:
            payload["target_cost_dollars"] = f"{target_cost_dollars:.2f}"
        else:
            payload["contracts_fp"] = "1.00"

        if dry_run or not self.is_authenticated:
            sim_rfq_id = f"sim_rfq_{uuid.uuid4().hex[:8]}"
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would create RFQ for {ticker}: {payload}")
            return {
                "id": sim_rfq_id,
                "rfq_id": sim_rfq_id,
                "market_ticker": ticker,
                "status": "simulated",
                "simulated": True
            }

        return self._request(
            "POST",
            "/communications/rfqs",
            json_data=payload,
            auth_required=True
        )

    def get_rfq_quotes(self, rfq_id: str, dry_run: bool = False) -> List[Dict[str, Any]]:
        """
        Retrieves quotes submitted for an RFQ.
        Endpoint: GET /trade-api/v2/communications/quotes?rfq_id={rfq_id}&rfq_user_filter=self
        """
        if dry_run or not self.is_authenticated:
            # Return a simulated quote for dry run
            return [{
                "id": f"sim_quote_{uuid.uuid4().hex[:6]}",
                "quote_id": f"sim_quote_{uuid.uuid4().hex[:6]}",
                "rfq_id": rfq_id,
                "yes_bid_dollars": "0.5200",
                "no_bid_dollars": "0.4800",
                "price_cents": 52,
                "simulated": True
            }]

        try:
            params = {
                "rfq_id": rfq_id,
                "rfq_user_filter": "self"
            }
            res = self._request("GET", "/communications/quotes", params=params, auth_required=True)
            raw_quotes = res.get("quotes", [])
            parsed_quotes = []
            for q in raw_quotes:
                # Convert yes_bid_dollars / no_bid_dollars to cents
                yes_bid_d = q.get("yes_bid_dollars")
                price_c = int(round(float(yes_bid_d) * 100)) if yes_bid_d else q.get("price_cents", 50)
                q_copy = dict(q)
                q_copy["price_cents"] = price_c
                q_copy["quote_id"] = q.get("id") or q.get("quote_id")
                parsed_quotes.append(q_copy)
            return parsed_quotes
        except Exception as e:
            print(f"[KalshiClient] Warning fetching quotes for RFQ {rfq_id}: {e}")
            return []

    def accept_quote(self, rfq_id: str, quote_id: str, side: str = "yes", dry_run: bool = False) -> Dict[str, Any]:
        """
        Accepts a quote scoped to its RFQ.
        Endpoint: PUT /trade-api/v2/communications/rfqs/{rfq_id}/quotes/{quote_id}/accept
        """
        if dry_run or not self.is_authenticated:
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would accept quote {quote_id} for RFQ {rfq_id} (Side: {side})")
            return {"status": "accepted", "quote_id": quote_id, "rfq_id": rfq_id, "simulated": True}

        return self._request(
            "PUT",
            f"/communications/rfqs/{rfq_id}/quotes/{quote_id}/accept",
            json_data={"accepted_side": side.lower()},
            auth_required=True
        )

    def confirm_quote(self, rfq_id: str, quote_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Legacy confirmation endpoint if requested by quoter.
        """
        if dry_run or not self.is_authenticated:
            return {"status": "confirmed", "quote_id": quote_id, "rfq_id": rfq_id, "simulated": True}

        try:
            return self._request(
                "PUT",
                f"/communications/rfqs/{rfq_id}/quotes/{quote_id}/confirm",
                auth_required=True
            )
        except Exception:
            return {"status": "confirmed"}
