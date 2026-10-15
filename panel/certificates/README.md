# Optional corporate HTTPS certificates

On networks with HTTPS inspection, the panel build may report
`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` while
pip connects to PyPI. Windows and the Linux build image have separate trust
stores; trusting a certificate on Windows alone does not add it to the image.

1. Obtain the approved HTTPS-inspection root CA certificate from your IT team.
   If it is already installed on Windows, export that specific approved CA from
   `certlm.msc` under **Trusted Root Certification Authorities > Certificates**,
   using **All Tasks > Export > Base-64 encoded X.509 (.CER)**. Export only the
   public certificate, without a private key. Use the CA certificate, rather
   than the PyPI site/leaf certificate.
2. Save the PEM/Base-64 certificate here as `company-root.crt`. Each `.crt` file
   must contain one certificate, starting with `-----BEGIN CERTIFICATE-----`.
   Renaming a Base-64 `.cer` export to `.crt` is sufficient; binary DER exports
   must be converted to PEM first. Add required approved intermediate CAs as
   separate `.crt` files.
3. From the repository root, run `server\scripts\run-setup.cmd` on Windows or
   `bash server/scripts/setup.sh` on Linux. Normal `docker compose up -d --build`
   also uses these certificates, but setup additionally prepares the local
   configuration needed to install the game later from the panel.

The build validates the certificate files, installs them alongside the default
Linux trust roots, and uses that bundle for pip. Certificate verification remains
enabled. Invalid certificate files fail the build. No `.env` changes are needed.
Remove a certificate and rebuild to remove that locally added trust.

Certificates here are ignored by Git. Only `.crt` files and this README are
included from this directory in the Docker build context. Never place private
keys or client credentials here. Public CAs remain in the resulting local image's
trust store, so that image contains the organization-specific trust configuration.

This configures only the panel image. It does not allow blocked Steam downloads
or change trust settings in the game/updater images, Docker Desktop or Windows.
