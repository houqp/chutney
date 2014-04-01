TestingTorNetwork 1
DataDirectory $dir
RunAsDaemon 1
ConnLimit $connlimit
Nickname $nick
ShutdownWaitLength 0
PidFile ${dir}/pid
Log notice file ${dir}/notice.log
Log info file ${dir}/info.log
ProtocolWarnings 1
SafeLogging 0
ControlPort $controlport
# password is chutneytest
HashedControlPassword 16:4B0D447F74E3A5DE607CBA129212F9FF364881547FED54C79A13EEEBD9
${authorities}

