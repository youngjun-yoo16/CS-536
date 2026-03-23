import os

from control import ControlConnection

server = "speedtest.fra1.de.leaseweb.net"

ctrl = ControlConnection(server)
ctrl.run_test()