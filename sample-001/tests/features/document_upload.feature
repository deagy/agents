@SAMPLE-001 @upload @security
Feature: Quarantined document upload
  Local users need uploads scanned before retrieval without exposing another user's data.

  Scenario Outline: Accepted files remain unavailable until clean
    Given an authenticated user in tenant "alpha"
    When the user uploads a <type> file using a new idempotency key
    Then the upload is pending scan
    And document content is not downloadable
    When the scanner reports the exact object clean
    And the promotion worker promotes the exact object
    Then document content is downloadable as an attachment

    Examples:
      | type      |
      | PDF       |
      | PNG       |
      | JPEG      |
      | UTF-8 text|

  Scenario: Canonical EICAR content is rejected
    Given an authenticated user uploads the canonical EICAR test file
    When the fake scanner examines the exact quarantined object
    Then the document is rejected
    And document content is not downloadable

  Scenario: Idempotency conflict is safe
    Given an authenticated user has uploaded a file with idempotency key "same-key"
    When that user uploads different content with idempotency key "same-key"
    Then the request fails with idempotency conflict
    And no second document is created
