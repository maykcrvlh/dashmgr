# dashmgr - Copyright (C) 2026 mayk.cloud e luniobr.com - SPDX-License-Identifier: GPL-3.0-or-later
# dashmgr - define a senha de acesso ao painel web (criado por mayk.cloud e luniobr.com).
# Grava SO o hash (PBKDF2-SHA256, 200 mil iteracoes) em senha_web.json; o programa aplica ao abrir.
param([string]$Destino = $PSScriptRoot)
$ErrorActionPreference = 'Stop'

function Ler-Senha([string]$msg) {
    $s = Read-Host $msg -AsSecureString
    $b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($b) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
}

function Pbkdf2([string]$senha, [byte[]]$salt) {
    try {
        $k = New-Object Security.Cryptography.Rfc2898DeriveBytes($senha, $salt, 200000, [Security.Cryptography.HashAlgorithmName]::SHA256)
        try { return $k.GetBytes(32) } finally { $k.Dispose() }
    } catch {
        # .NET antigo (sem SHA256 no Rfc2898DeriveBytes): implementacao padrao do PBKDF2
        Add-Type -TypeDefinition @"
using System; using System.Security.Cryptography; using System.Text;
public static class DashmgrKdf {
  public static byte[] Derivar(string senha, byte[] salt, int it) {
    using (var h = new HMACSHA256(Encoding.UTF8.GetBytes(senha))) {
      byte[] bloco = new byte[salt.Length + 4];
      Buffer.BlockCopy(salt, 0, bloco, 0, salt.Length); bloco[bloco.Length - 1] = 1;
      byte[] u = h.ComputeHash(bloco), t = (byte[])u.Clone();
      for (int i = 1; i < it; i++) { u = h.ComputeHash(u); for (int j = 0; j < t.Length; j++) t[j] ^= u[j]; }
      return t;
    }
  }
}
"@
        return [DashmgrKdf]::Derivar($senha, $salt, 200000)
    }
}

Write-Host ""
Write-Host "      Senha de acesso ao PAINEL WEB do dashmgr (minimo 6 caracteres)."
Write-Host "      Deixe em branco e tecle Enter para manter a senha atual."
while ($true) {
    $s1 = Ler-Senha "      Nova senha"
    if ([string]::IsNullOrEmpty($s1)) { Write-Host "      Senha atual mantida."; exit 0 }
    if ($s1.Length -lt 6) { Write-Host "      A senha precisa ter pelo menos 6 caracteres." -ForegroundColor Yellow; continue }
    $s2 = Ler-Senha "      Repita a senha"
    if ($s1 -cne $s2) { Write-Host "      As senhas nao conferem. Tente de novo." -ForegroundColor Yellow; continue }
    break
}
$salt = New-Object byte[] 16
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($salt)
$hash = Pbkdf2 $s1 $salt
$s1 = $null; $s2 = $null
$hex = { param($b) -join ($b | ForEach-Object { $_.ToString('x2') }) }
$json = '{"salt": "' + (& $hex $salt) + '", "senha_hash": "' + (& $hex $hash) + '"}'
if (-not (Test-Path $Destino)) { New-Item -ItemType Directory -Path $Destino | Out-Null }
[IO.File]::WriteAllText((Join-Path $Destino 'senha_web.json'), $json, (New-Object Text.UTF8Encoding $false))
Write-Host "      Nova senha definida (vale a partir da proxima abertura do programa)." -ForegroundColor Green
if (-not $env:DASHMGR_INSTALADOR) { Read-Host "      Reabra o dashmgr para aplicar. Tecle Enter para sair" | Out-Null }
exit 0
