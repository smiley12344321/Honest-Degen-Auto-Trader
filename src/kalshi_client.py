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
            dry_run: If True, simulates order placement without sending to API
        """
        client_oid = client_order_id or str(uuid.uuid4())
        side_clean = side.lower()
        price_dollars = f"{price_cents / 100.0:.4f}"

        payload = {
            "ticker": ticker,
            "client_order_id": client_oid,
            "side": side_clean,
            "action": "buy",
            "count_fp": count_fp,
            "price_dollars": price_dollars,
            "yes_price": price_cents if side_clean == "yes" else (100 - price_cents),
            "time_in_force": time_in_force,
            "type": "limit"
        }

        if dry_run or not self.is_authenticated:
            print(f"[KalshiClient] [DRY RUN / SIMULATED] Would place order: {payload}")
            return {
                "status": "simulated",
                "order_id": f"sim_{client_oid[:8]}",
                "client_order_id": client_oid,
                "ticker": ticker,
                "side": side_clean,
                "count_fp": count_fp,
                "price_cents": price_cents,
                "simulated": True
            }

        return self._request(
            "POST",
            "/portfolio/events/orders",
            json_data=payload,
            auth_required=True
        )

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """
        Fetches status of a placed order.
        """
        return self._request("GET", f"/portfolio/orders/{order_id}", auth_required=True)
