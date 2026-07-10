"""TON Connect ownership challenge endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from schemas import (
    WalletOwnershipChallengeRequest,
    WalletOwnershipChallengeResponse,
    WalletOwnershipProofRequest,
    WalletOwnershipProofResponse,
)
from services.wallet_ownership_proof import (
    WalletOwnershipProofConflict,
    WalletOwnershipProofFailure,
    create_ownership_challenge,
    verify_ownership_proof,
)


router = APIRouter(prefix="/api/wallets/ownership", tags=["wallet-ownership"])


@router.post("/challenges", response_model=WalletOwnershipChallengeResponse)
def create_challenge(
    payload: WalletOwnershipChallengeRequest,
    response: Response,
    session: Session = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return create_ownership_challenge(
            session, expected_wallet=payload.expected_wallet
        )
    except WalletOwnershipProofConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="Ownership challenge storage unavailable.") from exc


@router.post(
    "/challenges/{challenge_id}/verify",
    response_model=WalletOwnershipProofResponse,
)
def verify_challenge(
    payload: WalletOwnershipProofRequest,
    response: Response,
    challenge_id: str = Path(..., pattern=r"^[0-9a-f-]{36}$"),
    session: Session = Depends(get_session),
):
    response.headers["Cache-Control"] = "no-store"
    try:
        return verify_ownership_proof(
            challenge_id, payload.model_dump(), session
        )
    except WalletOwnershipProofConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except WalletOwnershipProofFailure as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(status_code=503, detail="Ownership proof storage unavailable.") from exc
