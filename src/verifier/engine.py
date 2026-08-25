"""Verification coordinator and liveness evaluation engine."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from src.core.types import (
    GenesisEvidence,
    HeadObservation,
    NetworkIdentity,
    VerificationResult,
)
from src.verifier.adapters.aptos import AptosAdapter
from src.verifier.adapters.base import ProtocolAdapter
from src.verifier.adapters.cometbft import CometBFTAdapter
from src.verifier.adapters.evm import EVMAdapter
from src.verifier.adapters.fuel import FuelAdapter
from src.verifier.adapters.starknet import StarknetAdapter
from src.verifier.adapters.substrate import SubstrateAdapter
from src.verifier.adapters.sui import SuiAdapter
from src.verifier.adapters.svm import SVMAdapter
from src.verifier.safe_url import SSRFValidationError, SafeURLValidator

logger = logging.getLogger(__name__)


class VerifierEngine:
    """Orchestrates multi-family protocol probing and liveness checks."""

    def __init__(self):
        self.adapters: Dict[str, ProtocolAdapter] = {
            "evm": EVMAdapter(),
            "cosmos": CometBFTAdapter(),
            "substrate": SubstrateAdapter(),
            "svm": SVMAdapter(),
            "starknet": StarknetAdapter(),
            "aptos": AptosAdapter(),
            "sui": SuiAdapter(),
            "fuel": FuelAdapter(),
        }

    def get_adapter(self, family: str) -> Optional[ProtocolAdapter]:
        return self.adapters.get(family.lower())

    async def probe_endpoint(self, endpoint: str, family: str = "evm") -> VerificationResult:
        """Executes read-only identity, head, and genesis probes against a candidate endpoint."""
        now = datetime.now(timezone.utc)
        
        # 1. SSRF and URL validation
        try:
            SafeURLValidator.validate_url(endpoint)
        except SSRFValidationError as e:
            return VerificationResult(
                endpoint=endpoint,
                success=False,
                error_type="private_target",
                error_detail=str(e),
                checked_at=now,
            )
        except Exception as e:
            return VerificationResult(
                endpoint=endpoint,
                success=False,
                error_type="invalid_url",
                error_detail=str(e),
                checked_at=now,
            )

        # 2. Lookup Adapter
        adapter = self.get_adapter(family)
        if not adapter:
            return VerificationResult(
                endpoint=endpoint,
                success=False,
                error_type="method_unsupported",
                error_detail=f"No protocol adapter registered for family '{family}'",
                checked_at=now,
            )

        # 3. Probe Identity, Head, Genesis
        try:
            identity = await adapter.identity(endpoint)
            head = None
            try:
                head = await adapter.head(endpoint)
            except Exception as e:
                logger.warning(f"Head probe failed for {endpoint}: {e}")

            genesis = None
            try:
                genesis = await adapter.genesis(endpoint)
            except Exception as e:
                logger.warning(f"Genesis probe failed for {endpoint}: {e}")

            return VerificationResult(
                endpoint=endpoint,
                success=True,
                identity=identity,
                head=head,
                genesis=genesis,
                checked_at=now,
            )
        except Exception as e:
            err_msg = str(e).lower()
            error_type = "unreachable"
            if "429" in err_msg or "rate limit" in err_msg:
                error_type = "rate_limited"
            elif "size limit" in err_msg:
                error_type = "oversized/malformed"

            return VerificationResult(
                endpoint=endpoint,
                success=False,
                error_type=error_type,
                error_detail=str(e),
                checked_at=now,
            )

    @staticmethod
    def evaluate_liveness(
        obs1: Tuple[HeadObservation, Optional[str]],
        obs2: Tuple[HeadObservation, Optional[str]]
    ) -> Tuple[bool, bool]:
        """Evaluates whether block height is advancing and identity is stable.
        
        Args:
            obs1: (HeadObservation, identity_fingerprint) at t0
            obs2: (HeadObservation, identity_fingerprint) at t1 (60-180s later)
            
        Returns:
            Tuple[is_advancing, is_identity_stable]
        """
        head1, fp1 = obs1
        head2, fp2 = obs2
        
        advancing = head2.block_height > head1.block_height
        identity_stable = (fp1 == fp2) if (fp1 and fp2) else True
        return advancing, identity_stable


verifier_engine = VerifierEngine()
