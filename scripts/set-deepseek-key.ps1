# AI Farm: save DEEPSEEK_API_KEY as a Windows *user* environment variable.
# The key is typed into a hidden prompt in THIS window only.
# It is never printed, never written to a file, never stored in PowerShell history.
$ErrorActionPreference = "Stop"
Write-Host ""
Write-Host "=== AI 农场：保存 DeepSeek Key 到你自己的环境变量 ===" -ForegroundColor Cyan
Write-Host "在下面粘贴你的 DeepSeek Key（右键或 Ctrl+V 粘贴），然后按回车。"
Write-Host "粘贴时屏幕上不会显示任何字符，这是正常的。不要加引号。" -ForegroundColor Yellow
$secure = Read-Host "DeepSeek Key" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim().Trim('"').Trim("'")
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ([string]::IsNullOrWhiteSpace($plain)) {
    Write-Host "没有输入内容，什么都没保存。关掉这个窗口重新来一次就行。" -ForegroundColor Red
} else {
    [Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", $plain, "User")
    $len = $plain.Length
    $plain = $null
    Write-Host ""
    Write-Host "已保存到用户环境变量 DEEPSEEK_API_KEY（长度 $len 个字符，内容不显示）。" -ForegroundColor Green
    Write-Host "现在可以关掉这个窗口，回到 Antigravity 说一声“设好了”。"
}
Write-Host ""
Read-Host "按回车关闭窗口"
