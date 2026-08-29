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
            # MLB & Baseball
            "KXMLBGAME", "KXMLBF5", "KXMLBF3", "KXMLBF7", "KXMLBRFI", "KXNPBRFI", "KXKBORFI", "KXMLB",
            "KXKBOGAME", "KXKBOTOTAL",
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
            "KXEPLGAME", "KXEPLTOTAL", "KXEPLBTTS", "KXEPL1H", "KXEPL2H", "KXEPLMATCH"
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
        Returns: { "yes": [[price_cents, count], ...], "no": [[price_cents, count], ...] }
        """
        res = self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})
        return res.get("orderbook", res)

    def get_best_ask_cents(self, ticker: str, side: str = "yes") -> Optional[int]:
        """
        Retrieves the best available ask price in cents for 'yes' or 'no'.
        """
        try:
            ob = self.get_orderbook(ticker, depth=3)
            # Kalshi orderbook structure has yes/no bids/asks
            # Buying 'yes' takes the best 'yes' ask (or 100 - best 'no' bid)
            if side.lower() == "yes":
                if "yes" in ob and ob["yes"]:
                    # Best yes price from book
                    return int(ob["yes"][0][0])
                elif "no" in ob and ob["no"]:
                    # Complementary price
                    return 100 - int(ob["no"][0][0])
            else:
                if "no" in ob and ob["no"]:
                    return int(ob["no"][0][0])
                elif "yes" in ob and ob["yes"]:
                    return 100 - int(ob["yes"][0][0])
            
            # Fallback to market top-level last_price or yes_ask
            mkt = self.get_market(ticker)
            if side.lower() == "yes":
                return mkt.get("yes_ask") or mkt.get("last_price")
            else:
                return mkt.get("no_ask") or (100 - (mkt.get("last_price") or 50))
        except Exception as e:
            print(f"[KalshiClient] Could not fetch orderbook for {ticker}: {e}")
            return None

    # ================= Authenticated Trading Methods =================

    def get_balance(self) -> Dict[str, Any]:
        """
        Retrieves account balance and available purchasing power.
        """
        return self._request("GET", "/portfolio/balance", auth_required=True)

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

        # Determine target exchange shard index for fallback
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

        # Strategy 1: Auto-routed payload (exchange_index = -1)
        auto_routed_payload = {
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
            "exchange_index": -1
        }

        # Strategy 2: Direct shard payload (exchange_index = target_shard)
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

        active_payload = direct_payload if (exchange_index is not None and exchange_index >= 0) else auto_routed_payload

        if dry_run or not self.is_authenticated:
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would place order (exchange_index={active_payload.get('exchange_index')}): {active_payload}")
            return {
                "status": "simulated",
                "order_id": f"sim_{client_oid[:8]}",
                "client_order_id": client_oid,
                "ticker": ticker,
                "side": side_clean,
                "count_fp": count_fp,
                "price_cents": price_cents,
                "exchange_index": active_payload.get("exchange_index"),
                "simulated": True
            }

        # 1. Try initial placement (Auto-routed or Direct)
        try:
            return self._request(
                "POST",
                "/portfolio/events/orders",
                json_data=active_payload,
                auth_required=True
            )
        except Exception as e:
            err_msg = str(e).lower()
            # If auto-routing failed or shard returned user_not_found/sharding
            if "user_not_found" in err_msg or "sharding" in err_msg:
                print(f"[KalshiClient] Shard routing requires collateral initialization on Shard {target_shard}. Attempting transfer...")
                try:
                    order_risk_cents = max(500, int(price_cents * float(count_fp) * 1.5))
                    self.transfer_to_shard(destination_shard=target_shard, amount_cents=order_risk_cents)
                    print(f"[KalshiClient] Successfully transferred {order_risk_cents}c to Shard {target_shard}. Retrying direct order placement...")
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
        """
        client_tid = str(uuid.uuid4())

        # 1. Try Subaccounts Transfer endpoint with client_transfer_id
        sub_payload = {
            "client_transfer_id": client_tid,
            "amount_cents": amount_cents,
            "from_subaccount": 0,
            "to_subaccount": 0,
            "exchange_index": destination_shard
        }
        try:
            return self._request(
                "POST",
                "/portfolio/subaccounts/transfer",
                json_data=sub_payload,
                auth_required=True
            )
        except Exception as e1:
            # 2. Try Intra Exchange Instance Transfer endpoint
            instance_payload = {
                "client_transfer_id": client_tid,
                "amount": amount_cents,
                "source_exchange_shard": source_shard,
                "destination_exchange_shard": destination_shard
            }
            return self._request(
                "POST",
                "/portfolio/intra_exchange_instance_transfer",
                json_data=instance_payload,
                auth_required=True
            )

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Fetches status of a placed order.
        """
        return self._request("GET", f"/portfolio/orders/{order_id}", auth_required=True)

    # ================= Parlay / Combo & RFQ Methods =================

    def get_multivariate_collections(self) -> List[Dict[str, Any]]:
        """
        Fetches available multivariate event collections for combo/parlay creation.
        """
        try:
            res = self._request("GET", "/multivariate_event_collections")
            return res.get("multivariate_event_collections", res.get("collections", []))
        except Exception as e:
            print(f"[KalshiClient] Warning querying multivariate collections: {e}")
            return []

    def create_or_get_combo_market(
        self,
        collection_ticker: str,
        selected_markets: List[Dict[str, str]],
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Creates or resolves a combo market from individual legs.
        selected_markets format: [{"market_ticker": "...", "event_ticker": "..."}, ...]
        """
        payload = {
            "selected_markets": selected_markets,
            "with_market_payload": True
        }
        if dry_run or not self.is_authenticated:
            sim_ticker = f"KXCOMBO-SIM-{uuid.uuid4().hex[:8]}"
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would create combo market in {collection_ticker}: {payload}")
            return {
                "market": {
                    "ticker": sim_ticker,
                    "title": f"Simulated Parlay ({len(selected_markets)} legs)",
                    "yes_ask": None,
                    "last_price": None
                },
                "ticker": sim_ticker,
                "simulated": True
            }

        return self._request(
            "POST",
            f"/multivariate_event_collections/{collection_ticker}",
            json_data=payload,
            auth_required=True
        )

    def create_rfq(
        self,
        ticker: str,
        target_cost_dollars: Optional[float] = None,
        contracts_fp: Optional[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Creates a Request for Quote (RFQ) to request market maker pricing on a combo/parlay.
        """
        payload: Dict[str, Any] = {"ticker": ticker}
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
                "rfq_id": sim_rfq_id,
                "ticker": ticker,
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
        """
        if dry_run or not self.is_authenticated:
            # Return a simulated quote for dry run
            return [{
                "quote_id": f"sim_quote_{uuid.uuid4().hex[:6]}",
                "rfq_id": rfq_id,
                "yes_bid": 48,
                "yes_ask": 52,
                "price_cents": 52,
                "simulated": True
            }]

        try:
            res = self._request("GET", f"/communications/rfqs/{rfq_id}/quotes", auth_required=True)
            return res.get("quotes", [])
        except Exception as e:
            print(f"[KalshiClient] Warning fetching quotes for RFQ {rfq_id}: {e}")
            return []

    def accept_quote(self, rfq_id: str, quote_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Step 1 of execution: Accepts a quote.
        """
        if dry_run or not self.is_authenticated:
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would accept quote {quote_id} for RFQ {rfq_id}")
            return {"status": "accepted", "quote_id": quote_id, "rfq_id": rfq_id, "simulated": True}

        return self._request(
            "PUT",
            f"/communications/rfqs/{rfq_id}/quotes/{quote_id}/accept",
            auth_required=True
        )

    def confirm_quote(self, rfq_id: str, quote_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """
        Step 2 of execution: Confirms the accepted quote to finalize the trade.
        """
        if dry_run or not self.is_authenticated:
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would confirm quote {quote_id} for RFQ {rfq_id}")
            return {"status": "confirmed", "quote_id": quote_id, "rfq_id": rfq_id, "simulated": True}

        return self._request(
            "PUT",
            f"/communications/rfqs/{rfq_id}/quotes/{quote_id}/confirm",
            auth_required=True
        )
