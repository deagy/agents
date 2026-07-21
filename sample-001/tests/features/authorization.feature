@SAMPLE-001 @authorization @regression
Feature: Tenant and owner isolation
  Document existence must not be disclosed outside its owner boundary.

  Scenario Outline: Non-owners receive indistinguishable not found responses
    Given a document owned by subject "owner" in tenant "alpha"
    When <actor> requests its metadata, content, or deletion
    Then every operation returns the stable not found response

    Examples:
      | actor                                      |
      | another subject in tenant alpha            |
      | subject owner in a different tenant        |
      | an authenticated user using a missing UUID |

  Scenario: A mutation assertion cannot be replayed
    Given a valid BFF mutation assertion
    When the same assertion is submitted twice
    Then exactly one request can consume its assertion identifier

  Scenario: Ambiguous request targets are rejected
    Given a signed request containing a query or encoded path separator
    When the document API validates the request
    Then the request is rejected before authorization data is used
