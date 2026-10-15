# Read only the public CA chains Windows already trusts for Python downloads.
# Dot-sourced by setup; no Windows certificate stores or TLS policies are changed.
function Prepare-PanelCertificates {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    if (-not ("Cs2Panel.WindowsTrust" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Security;
using System.Security.Authentication;
using System.Security.Cryptography.X509Certificates;

namespace Cs2Panel {
    public static class WindowsTrust {
        public static X509Certificate2[] CertificateAuthorities(
            X509Chain chain, SslPolicyErrors errors) {
            if (errors != SslPolicyErrors.None || chain == null)
                throw new AuthenticationException("Windows did not validate the HTTPS certificate.");
            var result = new List<X509Certificate2>();
            // Element zero is the site's leaf certificate, never a trust root.
            for (int i = 1; i < chain.ChainElements.Count; i++)
                result.Add(new X509Certificate2(chain.ChainElements[i].Certificate.RawData));
            return result.ToArray();
        }

        public static X509Certificate2[] Read(string address) {
            var result = new List<X509Certificate2>();
            var request = (HttpWebRequest)WebRequest.Create(address);
            request.Method = "HEAD";
            request.Timeout = 15000;
            request.ReadWriteTimeout = 15000;
            request.AllowAutoRedirect = false;
            request.KeepAlive = false;
            request.ConnectionGroupName = Guid.NewGuid().ToString("N");
            request.ServerCertificateValidationCallback = delegate(
                object sender, X509Certificate certificate,
                X509Chain chain, SslPolicyErrors errors) {
                if (errors != SslPolicyErrors.None || chain == null)
                    return false;
                result.AddRange(CertificateAuthorities(chain, errors));
                return true;
            };
            try {
                try {
                    using (var response = request.GetResponse()) { }
                } catch (WebException error) {
                    // A 403/404 still completes a validated TLS handshake.
                    if (error.Status != WebExceptionStatus.ProtocolError || error.Response == null)
                        throw;
                    error.Response.Close();
                }
                if (result.Count == 0)
                    throw new AuthenticationException("No verified CA chain was received.");
                return result.ToArray();
            } finally {
                request.ServicePoint.CloseConnectionGroup(request.ConnectionGroupName);
            }
        }
    }
}
'@
    }

    $directory = Join-Path $ProjectRoot "panel/certificates"
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    # Only our generated files are replaced; manually supplied CAs are preserved.
    Get-ChildItem -LiteralPath $directory -Filter "windows-pypi-*.crt" -File |
        Remove-Item -Force
    $written = @{}
    foreach ($address in @("https://pypi.org/simple/flask/", "https://files.pythonhosted.org/")) {
        try {
            foreach ($certificate in [Cs2Panel.WindowsTrust]::Read($address)) {
                try {
                    $thumbprint = $certificate.Thumbprint
                    if (-not $written.ContainsKey($thumbprint)) {
                        $base64 = [Convert]::ToBase64String(
                            $certificate.RawData, [Base64FormattingOptions]::InsertLineBreaks
                        )
                        $pem = "-----BEGIN CERTIFICATE-----`n$base64`n-----END CERTIFICATE-----`n"
                        $path = Join-Path $directory "windows-pypi-${thumbprint}.crt"
                        [IO.File]::WriteAllText($path, $pem, [Text.Encoding]::ASCII)
                        $written[$thumbprint] = $true
                    }
                } finally {
                    $certificate.Dispose()
                }
            }
        } catch {
            Write-Warning "Could not read Windows HTTPS trust for ${address}: $($_.Exception.Message)"
        }
    }
    Write-Host "Prepared $($written.Count) CA certificate(s) from verified Windows HTTPS connections."
    return $written.Count
}
