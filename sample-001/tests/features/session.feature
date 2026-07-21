@SAMPLE-001 @oidc @csrf
Feature: Local BFF session boundary
  Browser credentials remain server-side and mutations require origin-bound CSRF proof.

  Scenario: Authorization Code with PKCE creates a session
    Given the explicit local fake OIDC provider is running on loopback
    When a user completes authorization with matching state, nonce, and S256 verifier
    Then the BFF returns an opaque session cookie
    And the session response returns an in-memory CSRF token
    And no OIDC token is returned to browser code

  Scenario Outline: Invalid protocol proof fails closed
    Given an OIDC authentication attempt
    When the callback contains a mismatched <proof>
    Then no session is created

    Examples:
      | proof         |
      | state         |
      | nonce         |
      | PKCE verifier |

  Scenario: Development fakes refuse unsafe startup
    Given a production or Kubernetes environment indicator
    When a development adapter starts
    Then startup fails without falling back to a fake
