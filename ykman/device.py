# Copyright (c) 2015 Yubico AB
# All rights reserved.
#
#   Redistribution and use in source and binary forms, with or
#   without modification, are permitted provided that the following
#   conditions are met:
#
#    1. Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#    2. Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.


from .util import CAPABILITY, TRANSPORT, parse_tlv_list
from .driver import AbstractDriver
from .driver_ccid import open_device as open_ccid
from .driver_u2f import open_device as open_u2f
from .driver_otp import open_device as open_otp


YK4_CAPA_TAG = 0x01
YK4_SERIAL_TAG = 0x02
YK4_ENABLED_TAG = 0x03


class FailedOpeningDeviceException(Exception):
    pass


_NULL_DRIVER = AbstractDriver()


class YubiKey(object):
    """
    YubiKey device handle
    """
    device_name = 'YubiKey'
    capabilities = 0
    enabled = 0
    _serial = None

    def __init__(self, driver):
        if not driver:
            raise ValueError('No driver given!')
        self._driver = driver

        if driver.transport == TRANSPORT.U2F and driver.sky:
            self.device_name = 'Security Key by Yubico'
            self.capabilities = CAPABILITY.U2F
        elif self.version >= (4, 1, 0):
            self.device_name = 'YubiKey 4'
            self._parse_capabilities(driver.read_capabilities())
            if self.capabilities == 0x07:  # YK Edge has no use for CCID.
                self.device_name = 'YubiKey Edge'
                self.capabilities = CAPABILITY.OTP | CAPABILITY.U2F
        elif self.version >= (4, 0, 0):  # YK Plus
            self.device_name = 'YubiKey Plus'
            self.capabilities = CAPABILITY.OTP | CAPABILITY.U2F
        elif self.version >= (3, 0, 0):
            self.device_name = 'YubiKey NEO'
            if driver.transport == TRANSPORT.CCID:
                self.capabilities = driver.probe_capabilities_support()
            elif self.mode.has_transport(TRANSPORT.U2F) \
                or self.version >= (3, 3, 0):
                self.capabilities = CAPABILITY.OTP | CAPABILITY.U2F \
                    | CAPABILITY.CCID
            else:
                self.capabilities = CAPABILITY.OTP | CAPABILITY.CCID
        else:
            self.capabilities = CAPABILITY.OTP

        if not self.enabled:  # Assume everything supported is enabled.
            self.enabled = self.capabilities & ~sum(TRANSPORT)  # not transports
            self.enabled |= self.mode.transports  # ...unless they are enabled.

    def _parse_capabilities(self, data):
        if not data:
            return
        c_len, data = ord(data[0]), data[1:]
        data = data[:c_len]
        data = parse_tlv_list(data)
        if YK4_CAPA_TAG in data:
            self.capabilities = int(data[YK4_CAPA_TAG].encode('hex'), 16)
        if YK4_SERIAL_TAG in data:
            self._serial = int(data[YK4_SERIAL_TAG].encode('hex'), 16)
        if YK4_ENABLED_TAG in data:
            self.enabled = int(data[YK4_ENABLED_TAG].encode('hex'), 16)
        else:
            self.enabled = self.capabilities

    @property
    def version(self):
        return self._driver.version

    @property
    def serial(self):
        return self._serial or self._driver.serial

    @property
    def driver(self):
        return self._driver

    @property
    def transport(self):
        return self._driver.transport

    @property
    def mode(self):
        return self._driver.mode

    @mode.setter
    def mode(self, mode):
        if not self.has_mode(mode):
            raise ValueError('Mode not supported: %s' % mode)
        self.set_mode(mode)

    def has_mode(self, mode):
        return self.capabilities & mode.transports == mode.transports

    def set_mode(self, mode, cr_timeout=0, autoeject_time=None):
        flags = 0

        # If autoeject_time is set, then set the touch eject flag.
        if autoeject_time is not None:
            flags |= 0x80
        else:
            autoeject_time = 0

        # NEO < 3.3.1 (?) should always set 82 instead of 2.
        if self.version <= (3, 3, 1) and mode.code == 2:
            flags = 0x80
        self._driver.set_mode(flags | mode.code, cr_timeout, autoeject_time)
        self._driver._mode = mode

    def use_transport(self, transport):
        if self.transport == transport:
            return self
        if not self.mode.has_transport(transport):
            raise ValueError('%s transport not enabled!' % transport)
        my_mode = self.mode
        my_serial = self.serial

        del self._driver
        self._driver = _NULL_DRIVER

        dev = open_device(transport)
        if dev.serial and my_serial:
            assert dev.serial == my_serial
        assert dev.mode == my_mode
        return dev

    def __str__(self):
        return '{0} {1[0]}.{1[1]}.{1[2]} {2} [{3.name}] serial: {4} CAP: {5:x}' \
            .format(
                self.device_name,
                self.version,
                self.mode,
                self.transport,
                self.serial,
                self.capabilities
            )


def open_device(transports=sum(TRANSPORT)):
    dev = None
    try:
        if TRANSPORT.CCID & transports:
            dev = open_ccid()
        if TRANSPORT.OTP & transports and not dev:
            dev = open_otp()
        if TRANSPORT.U2F & transports and not dev:
            dev = open_u2f()
    except Exception as e:
        raise FailedOpeningDeviceException(e)

    return YubiKey(dev) if dev is not None else None