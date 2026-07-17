# Security and sensitive-data handling

Do not report vulnerabilities with real research data attached. Use synthetic
minimal examples and remove participant, project and infrastructure identifiers.

DigQDA is research software in pre-release. It does not itself authorize data
processing. Deployments must remain inside an approved trust boundary and must
control model endpoints, logs, temporary files and generated artifacts.

## Reporting

Report suspected vulnerabilities privately — do not open a public issue and do
not attach real research data. Use GitHub's private vulnerability reporting for this repository
(**Security → Report a vulnerability**); enable it once under the repository's
Security settings if it is not already active.

## Supported versions

Until the first tagged release the tree is `0.4.x`-draft. From the first SemVer
release, the latest minor line is supported.
