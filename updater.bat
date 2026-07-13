@echo off
:: updater.bat — chamado pelo DemandFlow para aplicar atualização
:: Argumentos: %1=pasta_nova  %2=pasta_destino  %3=caminho_exe

:: Aguarda o processo principal encerrar completamente
timeout /t 3 /nobreak >nul

:: Copia novos arquivos por cima dos antigos
:: /E = subpastas  /IS = sobrescreve mesmo arquivo idêntico  /IT = sobrescreve
:: /IM = sobrescreve arquivo modificado  /NFL /NDL /NJH /NJS = saída silenciosa
robocopy "%~1" "%~2" /E /IS /IT /IM /NFL /NDL /NJH /NJS

:: Reinicia o aplicativo
if exist "%~3" (
    start "" "%~3"
) else (
    start "" "%~2\DemandFlow.exe"
)

:: Limpa a pasta temporária de origem
rd /s /q "%~1" 2>nul

exit
