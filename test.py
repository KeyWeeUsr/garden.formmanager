import unittest

from os.path import abspath, basename, join, splitext as split_ext
from tempfile import mkstemp, mkdtemp
from os import remove, close, environ
from time import sleep

from itertools import combinations
try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen

from shutil import rmtree


class FormManagerTestCase(unittest.TestCase):
    _tmpfiles = []
    _fm_instance = None

    def setUp(self):
        environ['KIVY_FORM_DEBUG'] = '1'

    # basic class tests
    def test_singleton(self):
        from kivy.garden.formmanager import FormManager as FM

        comb = combinations(
            [FM() for i in range(3)], r=2
        )

        for a, b in comb:
            self.assertEqual(a, b)

    def test_kill(self):
        from kivy.garden.formmanager import FormManager as FM

        inst = []
        for i in range(3):
            fm = FM()
            fm.kill()
            inst.append(fm)

        for a, b in combinations(inst, r=2):
            self.assertNotEqual(a, b)

    # server tests
    def test_not_running(self):
        from kivy.garden.formmanager import FormManager
        fm = FormManager()
        self.assertFalse(fm.running)
        self.assertNotEqual(
            FormManager.get_manager(),
            None
        )

    def test_run(self):
        from kivy.garden.formmanager import FormManager
        fm = FormManager()
        self._fm_instance = fm

        # default class value until changed in run()
        self.assertEqual(fm.port, 0)

        fm.run()
        port = fm.port
        self.assertTrue(fm.running)
        self.assertTrue(port)

        fm.stop()
        self.assertFalse(fm.running)
        self.assertTrue(fm.port)
        self.assertEqual(port, fm.port)

        # remove instance
        fm.kill()

    def test_rerun(self):
        # Invalid File Descriptor -1 for socket
        # doesn't work, closed socket can't be reopen apparently
        # https://bugs.python.org/msg278691
        from kivy.garden.formmanager import FormManager
        fm = FormManager()
        self._fm_instance = fm

        # default class value until changed in run()
        self.assertEqual(fm.port, 0)

        fm.run()
        port = fm.port
        self.assertTrue(fm.running)
        self.assertTrue(port)

        fm.stop()
        self.assertFalse(fm.running)
        self.assertTrue(fm.port)
        self.assertEqual(port, fm.port)

        # assert the ValueError, because IFD -1
        # raises STDLIB selectors.py's _fileobj_to_fd
        with self.assertRaises(ValueError):
            fm.server.serve_forever()
        fm.stop()
        self.assertFalse(fm.running)
        self.assertTrue(fm.port)
        self.assertEqual(port, fm.port)

        # remove instance
        fm.kill()

    def test_dummy_post(self):
        # remove later when API is strict
        from kivy.garden.formmanager import FormManager

        fm = FormManager()
        self._fm_instance = fm
        fm.run()

        self._send_json(
            host='http://127.0.0.1',
            port=fm.port,
            data={"test": "value"}
        )

        fm.kill()

    def test_add_nonform(self):
        from kivy.garden.formmanager import FormManager, FormManagerException

        fm = FormManager()
        self._fm_instance = fm
        fm.run()

        tmpfd, tmpfn = mkstemp('.py')
        FormManagerTestCase._tmpfiles.append([tmpfd, tmpfn])
        form = object()

        with self.assertRaises(FormManagerException):
            fm.add_form(form)

        fm.kill()

    def test_add_remove_form(self):
        from kivy.garden.formmanager import FormManager, Form

        fm = FormManager()
        self._fm_instance = fm
        fm.run()

        tmpfd, tmpfn = mkstemp('.py')
        FormManagerTestCase._tmpfiles.append([tmpfd, tmpfn])
        form = Form(tmpfn)

        fm.add_form(form)
        self.assertIn(form.name, fm.forms)
        fm.remove_form(form)
        self.assertNotIn(form.name, fm.forms)

        fm.kill()

    # helper methods
    def _send_json(self, host, port, data):
        json = str(data)
        request = Request(
            host + ':' + str(port),
            bytearray(json, 'utf-8'),
            {'Content-Type': 'application/json'}
        )
        json = urlopen(request).read().decode()
        print('result:', json)

    def tearDown(self):
        # in case of assertion error, always kill the server
        if self._fm_instance:
            self._fm_instance.kill()
        environ.pop('KIVY_FORM_DEBUG')
        sleep(0.1)


class FormTestCase(unittest.TestCase):
    _tmpfiles = []
    _fm_instance = None

    form_template = (
        "from random import randint\n"
        "from kivy.config import Config\n"
        "Config.set('graphics', 'position', 'custom')\n"
        "Config.set('graphics', 'left', randint(0, 600))\n"
        "Config.set('graphics', 'top', randint(0, 600))\n"
        "from kivy.garden.formmanager import FormApp\n"
        "from kivy.lang import Builder\n"
        "from kivy.uix.boxlayout import BoxLayout\n"
        "Builder.load_string('''\n"
        "<Test>:\n"
        "    Button:\n"
        "        text: app.name\n"
        "''')\n"
        "class Test(BoxLayout):\n"
        "    pass\n"
        "class {0}(FormApp):\n"
        "    def build(self):\n"
        "        return Test()\n"
        "{0}().run()\n"
    )

    def test_name(self):
        from kivy.garden.formmanager import Form

        tmpfd, tmpfn = mkstemp('.py')
        FormTestCase._tmpfiles.append([tmpfd, tmpfn])

        form = Form(tmpfn)
        self.assertEqual(
            form.name,
            split_ext(basename(abspath(tmpfn)))[0]
        )

    def test_run_form(self):
        # needs more details
        from kivy.garden.formmanager import FormManager, Form

        fm = FormManager()
        self._fm_instance = fm
        fm.run()

        tmpdir = mkdtemp()

        tmp_form = join(tmpdir, 'form0.py')
        form_name = split_ext(basename(abspath(tmp_form)))[0]
        with open(tmp_form, 'w') as f:
            f.write(
                self.form_template.format(form_name.capitalize())
            )

        form = Form(tmp_form)
        fm.add_form(form)
        fm.run_form(form)

        # Form application is basically another Kivy app run in
        # a separate process, therefore we have to wait for it to load
        sleep(2)

        self.assertTrue(fm.forms[form.name]['active'])

        # remove form test?
        fm.kill()
        rmtree(tmpdir)

    def test_run_multiple_forms(self):
        # needs more details
        from kivy.garden.formmanager import FormManager, Form

        fm = FormManager()
        self._fm_instance = fm
        fm.run()

        tmpdir = mkdtemp()

        for i in range(3):
            tmp_form = join(tmpdir, 'form{}.py'.format(i + 1))
            form_name = split_ext(basename(abspath(tmp_form)))[0]
            with open(tmp_form, 'w') as f:
                f.write(
                    self.form_template.format(form_name.capitalize())
                )

            form = Form(tmp_form)
            fm.add_form(form)
            fm.run_form(form)

            # Form application is basically another Kivy app run in
            # a separate process, therefore we have to wait for it to load
            sleep(3)

            self.assertTrue(fm.forms[form.name]['active'])

        # remove form test?
        fm.kill()
        rmtree(tmpdir)

    def test_run_form_request_action(self):
        from kivy.garden.formmanager import FormManager, Form, FormManagerException

        fm = FormManager()
        self._fm_instance = fm
        fm.run()

        # request action on non-existing Form
        with self.assertRaises(FormManagerException):
            fm.request_action('form4', 'print', 'nope')

        self.assertEqual(fm.queue, {})

        tmpdir = mkdtemp()

        tmp_form = join(tmpdir, 'form4.py')
        form_name = split_ext(basename(abspath(tmp_form)))[0]
        with open(tmp_form, 'w') as f:
            f.write(
                self.form_template.format(form_name.capitalize())
            )

        form = Form(tmp_form)
        fm.add_form(form)
        fm.run_form(form)

        # Form application is basically another Kivy app run in
        # a separate process, therefore we have to wait for it to load
        sleep(2)

        self.assertTrue(fm.forms[form.name]['active'])

        # request action for Form1
        fm.request_action('form4', 'print', 'test')
        self.assertEqual(
            fm.queue,
            {'form4': [['print', 'test']]}
        )

        sleep(1)

        # after request the action is popped,
        # but Form remains in the queue as a key
        self.assertEqual(fm.queue, {"form4": []})

        # after the Form is removed, the key should too
        fm.remove_form(form)
        self.assertNotIn(form.name, fm.forms)
        self.assertEqual(fm.queue, {})

        fm.kill()
        rmtree(tmpdir)

    def test_run_form_request_call(self):
        from kivy.garden.formmanager import FormManager, Form, FormManagerException

        fm = FormManager()
        self._fm_instance = fm
        fm.run()
        self.assertEqual(fm.queue, {})

        tmpdir = mkdtemp()
        tmp_form = join(tmpdir, 'form5.py')
        form_name = split_ext(basename(abspath(tmp_form)))[0]
        with open(tmp_form, 'w') as f:
            f.write(
                self.form_template.format(form_name.capitalize())
            )

        form = Form(tmp_form)
        fm.add_form(form)
        fm.run_form(form)

        # Form application is basically another Kivy app run in
        # a separate process, therefore we have to wait for it to load
        sleep(2)

        self.assertTrue(fm.forms[form.name]['active'])

        # request action for Form1
        fm.request_action('form5', 'call', ['self', 'open_settings'])
        self.assertEqual(
            fm.queue,
            {'form5': [['call', ['self', 'open_settings']]]}
        )

        sleep(1)

        # after request the action is popped,
        # but Form remains in the queue as a key
        self.assertEqual(fm.queue, {"form5": []})

        # after the Form is removed, the key should too
        fm.remove_form(form)
        self.assertNotIn(form.name, fm.forms)
        self.assertEqual(fm.queue, {})

        fm.kill()
        rmtree(tmpdir)

    def tearDown(self):
        # in case of assertion error, always kill the server
        if self._fm_instance:
            self._fm_instance.kill()
        sleep(1)


def tearDownModule():
    # throw away all temporary files after testing
    # therefore nothing should use the files here
    for desc, tmp in FormManagerTestCase._tmpfiles:
        close(desc)
        remove(tmp)
    for desc, tmp in FormTestCase._tmpfiles:
        close(desc)
        remove(tmp)
        


if __name__ == '__main__':
    unittest.main()
