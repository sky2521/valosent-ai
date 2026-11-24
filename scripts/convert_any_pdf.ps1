param (
    [string]$docx = "C:\Users\sky\Videos\VALOSENT_AI\VALOSENT_AI\docs\VALOSENT_AI_Project_Report.docx",
    [string]$pdf = "C:\Users\sky\Videos\VALOSENT_AI\VALOSENT_AI\docs\VALOSENT_AI_Project_Report.pdf"
)

$ErrorActionPreference = "Stop"
Write-Host "Converting $docx to $pdf..."
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = [Microsoft.Office.Interop.Word.WdAlertLevel]::wdAlertsNone

try {
    $doc = $word.Documents.Open($docx, $false, $true)
    $wdFormatPDF = 17
    $doc.SaveAs([ref]$pdf, [ref]$wdFormatPDF)
    $doc.Close([ref]$false)
    Write-Host "Successfully generated: $pdf"
}
finally {
    $word.Quit([ref]$false)
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
