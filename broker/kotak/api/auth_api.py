import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def authenticate_broker(mobile_number, totp, mpin):
    """
    Authenticate with Kotak using TOTP and MPIN flow.

    Steps:
    1. Login with TOTP to get View token and sid
    2. Validate with MPIN to get Trading token and sid

    Args:
        mobile_number: Mobile number with +91 prefix
        totp: 6-digit TOTP from authenticator app
        mpin: 6-digit trading MPIN

    Returns:
        Tuple of (auth_string, error_message)
        auth_string format: "trading_token:::trading_sid:::base_url:::access_token"

        Components:
        - trading_token: Used in 'Auth' header for API calls
        - trading_sid: Used in 'Sid' header for API calls
        - base_url: Base URL for all API endpoints (e.g., https://cis.kotaksecurities.com)
        - access_token: Original API access token (kept for reference)
    """
    try:
        logger.info("Starting Kotak TOTP authentication flow")

        # Get UCC from BROKER_API_KEY and access_token from BROKER_API_SECRET
        from utils.config import get_broker_api_key, get_broker_api_secret

        ucc = get_broker_api_key()
        access_token = get_broker_api_secret()

        if not ucc:
            logger.error("BROKER_API_KEY (UCC) is not configured")
            return None, "BROKER_API_KEY (UCC) is required in .env file"

        if not access_token:
            logger.error("BROKER_API_SECRET (Access Token) is not configured")
            return None, "BROKER_API_SECRET (Access Token) is required in .env file"

        logger.debug(f"Parsed UCC: {ucc}, Access Token length: {len(access_token)}")

        # Ensure mobile number has +91 prefix
        # Handle all cases: +919876543210, 919876543210, 9876543210
        mobile_number = mobile_number.strip()
        # Remove any existing +91 or 91 prefix
        mobile_number = mobile_number.replace("+91", "").replace(" ", "")
        if mobile_number.startswith("91") and len(mobile_number) == 12:
            mobile_number = mobile_number[2:]  # Remove leading 91
        # Add +91 prefix
        mobile_number = f"+91{mobile_number}"

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Step 1: Login with TOTP
        payload = json.dumps({"mobileNumber": mobile_number, "ucc": ucc, "totp": totp})

        headers = {
            "Authorization": access_token,
            "neo-fin-key": "neotradeapi",
            "Content-Type": "application/json",
        }

        logger.debug(f"TOTP Login Request - Mobile: {mobile_number[:5]}***, UCC: {ucc}")

        response = client.post(
            "https://mis.kotaksecurities.com/login/1.0/tradeApiLogin",
            headers=headers,
            content=payload,
            timeout=15,
        )

        logger.debug(f"TOTP Login Response Status: {response.status_code}")

        data_dict = json.loads(response.text)
        logger.debug(f"TOTP Login Response fields: {list(data_dict)}")

        # Check for errors in TOTP login
        if "data" not in data_dict or data_dict.get("data", {}).get("status") != "success":
            logger.warning("Kotak declined the authenticator login")
            return None, "Kotak could not verify the login. Retry with a fresh authenticator code."

        # Extract View token and sid
        view_token = data_dict["data"]["token"]
        view_sid = data_dict["data"]["sid"]

        logger.info("TOTP Login successful, proceeding with MPIN validation")

        # Step 2: Validate with MPIN
        payload = json.dumps({"mpin": mpin})

        headers = {
            "Authorization": access_token,
            "neo-fin-key": "neotradeapi",
            "sid": view_sid,
            "Auth": view_token,
            "Content-Type": "application/json",
        }

        logger.debug("MPIN Validation Request initiated")

        response = client.post(
            "https://mis.kotaksecurities.com/login/1.0/tradeApiValidate",
            headers=headers,
            content=payload,
            timeout=15,
        )

        logger.debug(f"MPIN Validation Response Status: {response.status_code}")

        data_dict = json.loads(response.text)
        logger.debug(f"MPIN Validation Response fields: {list(data_dict)}")

        # Check for errors in MPIN validation
        if "data" not in data_dict or data_dict.get("data", {}).get("status") != "success":
            logger.warning("Kotak declined the trading-session validation")
            return (
                None,
                "Kotak trading login did not complete. Check the private MPIN configuration.",
            )

        # Extract Trading token, sid, and baseUrl
        trading_token = data_dict["data"]["token"]
        trading_sid = data_dict["data"]["sid"]
        base_url = data_dict["data"].get("baseUrl", "")
        # Which data centre this account lives in ("E43", "E21", ...). Kotak
        # resolves the market-data feed host per data centre from a config
        # service, so streaming needs this to know whether the account is
        # routed to SFeed or cdtstream. See streaming/kotak_feed_config.py.
        data_center = data_dict["data"].get("dataCenter", "")

        if not base_url:
            logger.warning("baseUrl not found in MPIN validation response, API calls may fail")
        if not data_center:
            logger.warning(
                "dataCenter not found in MPIN validation response; market-data streaming "
                "will fall back to the default SFeed endpoint"
            )

        logger.info("Kotak TOTP authentication completed successfully")
        logger.debug(f"Base URL for API calls: {base_url}, data centre: {data_center}")

        # Auth string: trading_token:::trading_sid:::base_url:::access_token:::data_center
        #
        # data_center is appended, never inserted. Tokens issued before it was
        # captured have four parts and are still valid, so every reader takes
        # the first four positionally and treats a missing fifth as unknown -
        # inserting it anywhere else would invalidate every stored token and
        # force all existing users to log in again.
        auth_string = (
            f"{trading_token}:::{trading_sid}:::{base_url}:::{access_token}:::{data_center}"
        )
        logger.debug(f"AUTH TOKEN CREATED for base URL: {base_url}")

        return auth_string, None

    except (KeyError, json.JSONDecodeError):
        logger.exception("Kotak login response was incomplete")
        return None, "Kotak returned an incomplete login response. Retry later."
    except httpx.HTTPError:
        logger.exception("Kotak login connection failed")
        return None, "Could not reach Kotak login. Check the connection and retry."
    except Exception:
        logger.exception("Kotak authentication did not complete")
        return None, "Kotak login did not complete. Retry with a fresh authenticator code."
