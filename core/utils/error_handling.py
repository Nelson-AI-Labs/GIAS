# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The GIAS Authors

"""
Standardized error handling utilities for GIAS.

This module provides consistent error response patterns across all API modules
and components, ensuring uniform error representation throughout the application.
"""

import logging
from typing import Any, Dict, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """Standard error codes for GIAS API responses."""
    NETWORK_ERROR = "network_error"
    TIMEOUT_ERROR = "timeout_error"
    PARSE_ERROR = "parse_error"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    API_ERROR = "api_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    AUTH_ERROR = "auth_error"
    UNKNOWN_ERROR = "unknown_error"


def create_error_response(
    code: ErrorCode,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a standardized error response dictionary.

    Args:
        code: The error code from ErrorCode enum
        message: Human-readable error message
        details: Optional additional details about the error
        source: Optional source identifier (e.g., 'GBIF', 'IUCN')

    Returns:
        Standardized error response dictionary
    """
    response = {
        "status": "error",
        "error_code": code.value,
        "message": message,
        "details": details or {}
    }

    if source:
        response["source"] = source

    return response


def create_success_response(
    data: Any,
    source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Create a standardized success response dictionary.

    Args:
        data: The response data
        source: Optional source identifier (e.g., 'GBIF', 'IUCN')
        metadata: Optional metadata about the response

    Returns:
        Standardized success response dictionary
    """
    response = {
        "status": "success",
        "data": data
    }

    if source:
        response["source"] = source

    if metadata:
        response["metadata"] = metadata

    return response


def create_not_found_response(
    entity: str,
    identifier: str,
    source: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a standardized not-found response.

    Args:
        entity: Type of entity not found (e.g., 'species', 'record')
        identifier: The identifier that was searched for
        source: Optional source identifier

    Returns:
        Standardized not-found error response
    """
    return create_error_response(
        code=ErrorCode.NOT_FOUND,
        message=f"{entity.capitalize()} not found: {identifier}",
        details={"entity": entity, "identifier": identifier},
        source=source
    )


def log_and_create_error(
    code: ErrorCode,
    message: str,
    exception: Optional[Exception] = None,
    details: Optional[Dict[str, Any]] = None,
    source: Optional[str] = None
) -> Dict[str, Any]:
    """
    Log an error and create a standardized error response.

    Combines logging and error response creation for common error handling pattern.

    Args:
        code: The error code from ErrorCode enum
        message: Human-readable error message
        exception: Optional exception that caused the error
        details: Optional additional details
        source: Optional source identifier

    Returns:
        Standardized error response dictionary
    """
    log_message = message
    if exception:
        log_message = f"{message}: {exception}"
        if details is None:
            details = {}
        details["exception_type"] = type(exception).__name__

    if code in (ErrorCode.NETWORK_ERROR, ErrorCode.TIMEOUT_ERROR, ErrorCode.API_ERROR):
        logger.error(log_message)
    elif code == ErrorCode.NOT_FOUND:
        logger.warning(log_message)
    else:
        logger.error(log_message)

    return create_error_response(
        code=code,
        message=message,
        details=details,
        source=source
    )
