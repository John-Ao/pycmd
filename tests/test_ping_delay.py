import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from pycmd import Runtime
from pycmd.ping_delay import delay


class PingDelayTests(unittest.TestCase):
    def test_loopback_equivalents(self):
        for arg in ('/n 4 127.1','127.0.0.1 -n 4','-n 4 localhost','-4 /w 4000 127.1 /n 4',
                    '-6 ::1 -n 4','/n 4 127.0.1','/n 4 2130706433','LOCALHOST. /n 4'):
            with self.subTest(arg=arg):self.assertEqual(delay(arg),(3,0))
        self.assertEqual(delay('127.1'),(3,0))
        self.assertEqual(delay('-n 1 -w 4000 127.1'),(0,0))
        self.assertEqual(delay('-n 5 127.1'),(4,0))

    def test_explicit_timeout_recipe(self):
        for target in ('192.0.2.1','198.51.100.1','203.0.113.1'):
            self.assertEqual(delay('-n 1 -w 1250 '+target),(1.25,1))

    def test_reject_unknown_before_sleep_even_allow_external(self):
        for arg in ('','-t 127.1','-n 0 127.1','-n -1 127.1','-n 1.5 127.1',
                    '-n 4294967296 127.1','-w -1 127.1','-w 127.1','-n 2 -n 3 127.1',
                    '127.1 extra','example.com','8.8.8.8','-6 127.1','-4 ::1',
                    '-n 1 -w 1000 192.168.1.1','-n 2 -w 1000 192.0.2.1'):
            with self.subTest(arg=arg),patch('pycmd.ping_delay.time.sleep') as sleep:
                rt=Runtime(allow_external=True)
                self.assertEqual(rt.command('ping '+arg+' >nul'),1)
                self.assertEqual(rt.state.errorlevel,1)
                self.assertIn(b'PING:',rt.streams.table[2].getvalue())
                sleep.assert_not_called()

    def test_batch_aliases_expansion_and_redirection(self):
        for command in ('ping/n %N% 127.1','PING.EXE /n %N% localhost','ping 127.0.0.1 -n %N%'):
            with self.subTest(command=command),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'delay.bat'
                path.write_text('@echo off\nset N=4\n'+command+' >nul 2>&1\necho RESULT=%errorlevel%\n')
                rt=Runtime(cwd=folder);rt.state.errorlevel=77
                with patch('pycmd.ping_delay.time.sleep') as sleep:rt.batch(path)
                sleep.assert_called_once_with(3)
                self.assertEqual(rt.streams.table[1].getvalue(),b'RESULT=0\r\n')
                self.assertEqual(rt.streams.table[2].getvalue(),b'')

    def test_conditional_timeout_status_and_help(self):
        rt=Runtime()
        with patch('pycmd.ping_delay.time.sleep') as sleep:
            rt.command('ping -n 1 -w 4000 192.0.2.1 >nul || echo TIMEOUT')
        sleep.assert_called_once_with(4)
        self.assertEqual(rt.state.errorlevel,1)
        self.assertEqual(rt.streams.table[1].getvalue(),b'TIMEOUT\r\n')
        rt.command('ping /?')
        self.assertIn(b'Delay emulation only',rt.streams.table[1].getvalue())

    def test_interrupt_retains_traceback(self):
        rt=Runtime(traceback=True)
        with patch('pycmd.ping_delay.time.sleep',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
            rt.command('ping/n 4 127.1 >nul')
        self.assertIn(b'KeyboardInterrupt',rt.streams.table[2].getvalue())


if __name__=='__main__':unittest.main()
