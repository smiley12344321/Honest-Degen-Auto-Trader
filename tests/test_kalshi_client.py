import base64
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding

from src.kalshi_client import KalshiClient


@pytest.fixture
def test_rsa_key_pair():
    """Generates an ephemeral RSA private/public key pair for tests."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )
    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")
    
    return private_key, pem_private


class TestKalshiClient:

    def test_rsa_pss_signature(self, test_rsa_key_pair):
        priv_key_obj, pem_str = test_rsa_key_pair
        client = KalshiClient(api_key_id="test-key-id", private_key_pem=pem_str)
        
        assert client.is_authenticated is True
        
        timestamp = "1724540000000"
        method = "POST"
        path = "/trade-api/v2/portfolio/events/orders"
        
        sig_b64 = client.sign_request(timestamp, method, path)
        sig_bytes = base64.b64decode(sig_b64)
        
        # Verify signature with public key
        pub_key = priv_key_obj.public_key()
        msg = f"{timestamp}{method}{path}".encode("utf-8")
        
        # Should not raise cryptography.exceptions.InvalidSignature
        pub_key.verify(
            sig_bytes,
            msg,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )

    def test_auth_headers_generation(self, test_rsa_key_pair):
        _, pem_str = test_rsa_key_pair
        client = KalshiClient(api_key_id="my-key-uuid", private_key_pem=pem_str)
        headers = client._get_auth_headers("GET", "/trade-api/v2/portfolio/balance")
        
        assert headers["KALSHI-ACCESS-KEY"] == "my-key-uuid"
        assert "KALSHI-ACCESS-TIMESTAMP" in headers
        assert "KALSHI-ACCESS-SIGNATURE" in headers
        assert headers["Content-Type"] == "application/json"

    def test_dry_run_create_order(self):
        client = KalshiClient()  # Unauthenticated
        order = client.create_order(
            ticker="KXMLBGAME-24AUG24-TBR-DET-TBR",
            side="yes",
            count_fp="1.32",
            price_cents=57,
            dry_run=True
        )
        
        assert order["status"] == "simulated"
        assert order["ticker"] == "KXMLBGAME-24AUG24-TBR-DET-TBR"
        assert order["side"] == "yes"
        assert order["count_fp"] == "1.32"
        assert order["price_cents"] == 57
        assert order["simulated"] is True

    def test_dry_run_combo_rfq_workflow(self):
        client = KalshiClient()  # Unauthenticated
        
        # 1. Create combo market
        selected_markets = [
            {"market_ticker": "KXTENNIS-1", "event_ticker": "EVENT-1"},
            {"market_ticker": "KXTENNIS-2", "event_ticker": "EVENT-2"}
        ]
        combo_res = client.create_or_get_combo_market("KXSPORTSCOMBO", selected_markets, dry_run=True)
        assert combo_res["simulated"] is True
        combo_ticker = combo_res["ticker"]

        # 2. Create RFQ
        rfq_res = client.create_rfq(combo_ticker, target_cost_dollars=1.00, dry_run=True)
        assert rfq_res["simulated"] is True
        rfq_id = rfq_res["rfq_id"]

        # 3. Get Quotes
        quotes = client.get_rfq_quotes(rfq_id, dry_run=True)
        assert len(quotes) >= 1
        quote_id = quotes[0]["quote_id"]

        # 4. Accept & Confirm
        acc = client.accept_quote(rfq_id, quote_id, dry_run=True)
        assert acc["status"] == "accepted"

        conf = client.confirm_quote(rfq_id, quote_id, dry_run=True)
        assert conf["status"] == "confirmed"
