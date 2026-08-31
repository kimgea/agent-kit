# Review policy

Authentication tokens must expire within one hour. A touched configuration
that exceeds this security policy must not ship. Changing authentication token
lifetime is security-sensitive even when restoring the stated policy.
