'''
Form Manager
============

.. warning::

    This is a *VERY* experimental attempt to make Kivy work in a mode with
    multiple windows independent on each other which can communicate together.


.. note::

    This attempt was written mainly in Python 3, therefore it can happen
    some calls will crash the app for now.


The :class:`FormManager` is not a Kivy widget. It's a class that handles
multiple :class:`~kivy.app.App` instances running in separate processes. This
behavior is known like having multiple "windows" for a single appliction and is
quite commonly known on Microsoft Windows as an application with "forms".

Kivy already has a :class:`~kivy.core.window.Window` class and works by default
only with a single-window type of applications, therefore instead rewriting
:class:`~kivy.core.window.Window` to support multiple windows by default the
next usable way is to create a manager similar to
:class:`~kivy.uix.screenmanager.ScreenManager` which would handle this default
state with spawning multiple single-window applications and handle the
communication between them. You can imagine it like handling a class instance
communication through an :class:`~kivy.app.App` instance via
``App.get_running_app()``, but a little bit broader.


Basic Usage
-----------

Let's construct a Form Manager with 4 named screens. Unlike with
:class:`~kivy.uix.screenmanager.ScreenManager`, with form manager you don't
need to specify a name for a :class:`Form`, because it's taken directly from
the :class:`~kivy.app.App` class name the same way like
a :class:`~kivy.core.window.Window` title. What you *need* to specify is the
filename of the :class:`Form`.::

    from kivy.uix.formmanager import FormManager, Form

    # Get the manager, it's a singleton
    fm = FormManager()

    # run the manager/server for communication
    fm.run()

    # Add few Forms
    for i in range(3):
        # load Form application from file
        form = Form('/path/to/form{}.py'.format(i + 1))

        # add Form instance to FormManager
        fm.add_form(form)

        # run the Form application
        rm.run_form(form)

    # make 'form1' print something
    fm.request_action('form1', 'print', 'Hello, World')

    # stop the server if necessary for some reason, can't be re-run
    fm.stop()

    # When done with application,
    # simply kill the FormManager and the Forms will exit
    fm.kill()  # makes FormManager instance unusable


Examples
--------

None, yet. See unittest for now.


Process tree
------------

This is a basic overview of what's happening under the hood to identify bugs
in the implementation easier. More description probably soon.::

                                _______________
                                |             |
                                | FormManager |
                                |  (server)   |
                                |_____________|
                                       |
                                       v
                               create instance fm
                                       |
                                       v
                      +-----------  fm.run()
                      |                |
                      |                v
                      +------  create TCP server  -> request free port from OS
                      |      (run in daemon Thread)
                      |                |
                      |                v
                      |          form = Form()
       manager alive? +----  create Form instance
                      |                |
                      |                v
                      |        fm.add_form(form)
                      +---  add Form to FormManager
                      |                |
                      |                v
                      |        fm.run_form(form)
                      +-----  run Form in manager  <-------<-------<-------<--+
                          (run App process in Thread)                         |
                                       |                                      ^
                         +-------------+-------------+                        |
                     ____|____     ____|____     ____|____                    |
                     |       |     |       |     |       |                    |
                     | Form1 |     | Form2 |     | Form3 |                    ^
                     |_______|     |_______|     |_______|                    |
                         |             |             |                        |
                     ____|____     ____|____     ____|____                    |
                     |       |     |       |     |       |                    ^
                     |  App  |     |  App  |     |  App  |                    |
                     |_______|     |_______|     |_______|                    |
                         |             |             |                        |
                         +-------------+-------------+                        ^
                                       |                                      |
                                       v                                      |
                               initialize FormApp  -> load limited symbols    |
                          (requires PORT to listen to)                        ^
                                       |                                      |
                                       v                                      |
                        register Form name in FormManager                     |
                       (mark Form as active in FormManager)                   ^
                                       |                                      |
                                       v                                      |
     +--->------->------->  start asking for actions  -> do POST requests to  |
     ^                        (via dictionary/JSON)      FormManager server   ^
     |                                 |                                      |
     |                                 v                                      |
     |                         action is defined                              |
     ^                                 |                                      ^
     |                            yes  |--- no --->  ignore action            |
     |                                 |                                      |
     |                                 v                                      |
     ^                          quitting action                               ^
     |                                 |                                      |
     |                             no / \  yes --->  App.stop()               |
     |     execute action with       /   \                                    |
     ^    (kw)args from request     /     \                                   ^
     |                             /       \                                  |
     |                            |         |                                 |
     |                  send status back to FormManager                       |
     ^                            |         |                                 ^
     |     and repeat             v        /                                  |
     +---<-------<-------<--------+       /                                   |
                                         /                                    |
                                        /                                     ^
                                       |                                      |
                                       v                                      |
                      ask FormManager to unregister Form                      |
                                       |                                      ^
                                       v                                      |
                    unregistered form can't receive actions                   |
                                       |                                      |
                                       v                                      ^
                                run Form again                                |
                                       |                                      |
                                   no  |--- yes ---->------->------->------->-+
                                       |
                                       v
                             fm.remove_form(form)  ---------+
                         remove Form from FormManager       |
                                       |                    |
                                       v                    |
                                   fm.stop()  --------------+  manager alive?
                          shutdown server if running        |
                                       |                    |
                                       v                    |
                                   fm.kill()  --------------+
                                 call fm.stop()
                           mark instance as unusable
                                       |
                                       v
                              FormManager is dead,
                              instance is unusable


Known "bugs"
------------

* ``ConnectionResetError`` if the server is killed too soon (example might
  occur in the unittest), for example ``WinError 10054``.
'''

__all__ = ('Form', 'FormManager')

# server
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    import SocketServer
except ImportError:
    import socketserver as SocketServer
from threading import Thread

# parsing
from ast import literal_eval
from os.path import abspath, basename, splitext as split_ext

# processes
from subprocess import call
from sys import executable as python
from os import environ

# Kivy stuff
from kivy.app import App
from kivy.clock import Clock
from kivy.logger import Logger


# print simple and useful trace of pinging
# between manager <-> forms
DEBUG = environ.get('KIVY_FORM_DEBUG')


# necessary to make things more readable
class FormManagerException(Exception):
    pass


class FormManager:
    __running = False
    __killed = False

    # the current running manager instance
    __manager = None

    # form instances added to the manager
    __forms = []

    # currently active forms
    # (running apps that pinged the manager back)
    __active_forms = []

    # currently running processes for Forms
    __processes = {}

    # queue for form actions
    __queue = {}

    # server properties
    __port = 0

    def __new__(cls):
        # Force FormManager to be singleton
        if FormManager.__manager:
            return FormManager.__manager
        else:
            # overwrite private variables
            # when creating a new instance
            FormManager.__forms = []
            FormManager.__active_forms = []
            FormManager.__processes = {}
            FormManager.__queue = {}
            return super(FormManager, cls).__new__(cls)

    def __init__(self, port=0, **kwargs):
        # assign singleton instance
        FormManager.__manager = self

        # get free port from OS if not specified
        self.__port = port
        self.server = None

    def __create_server(self):
        # run on localhost and request a free port
        # (by default at least)
        self.server = SocketServer.TCPServer(
            ('127.0.0.1', self.__port), FormServerHandler
        )

    # properties
    @staticmethod
    def get_manager():
        # FormManager > App
        # if no instance is available the App won't run
        return FormManager.__manager

    @property
    def killed(self):
        return self.__killed

    @property
    def running(self):
        return self.__running

    @property
    def port(self):
        return self.__port

    @property
    def forms(self):
        forms = {}
        for ins in self.__forms:
            forms[ins.name] = {
                "active": ins.name in self.__active_forms,
                "process": None
            }

        return forms

    @property
    def queue(self):
        return self.__queue

    # public methods
    def run(self):
        # ignore a killed manager
        # force user to create a new one
        if self.__killed:
            return

        if not self.server:
            self.__create_server()

        # serve forever in a separate thread
        # so that it doesn't block the main one
        self._server_thread = Thread(
            target=self.server.serve_forever
        )
        self._server_thread.daemon = True
        self._server_thread.start()
        self.__port = self.server.server_address[1]

        self.__running = True
        return self.__port

    def stop(self):
        # ignore a killed manager
        # force user to create a new one
        if self.__killed:
            return

        if self.server:
            # shutdown or WinError 10038
            #
            # docs say something else though:
            #   "must be called while serve_forever()
            #    is running in another thread,
            #    or it will deadlock."
            self.server.shutdown()
            self.server.server_close()
        self.__running = False

    def kill(self):
        # ignore a killed manager
        # force user to create a new one
        if self.__killed:
            return

        self.stop()
        self.__killed = True
        FormManager.__manager = None

    def add_form(self, form):
        # ignore a killed manager
        # force user to create a new one
        if self.__killed:
            return

        if not isinstance(form, Form):
            raise FormManagerException(
                'FormManager accepts only Form instances.'
            )

        # weakref it later
        if form in self.__forms:
            raise FormManagerException(
                "This instance of a Form "
                "already exists in the FormManager."
            )
        self.__forms.append(form)

    def remove_form(self, form):
        # ignore a killed manager
        # force user to create a new one
        if self.__killed:
            return

        if form not in self.__forms:
            return

        if form.name in self.__queue:
            del self.__queue[form.name]
        self.__forms.remove(form)

    def run_form(self, form):
        '''Runs a Form in a separate process. After the process
        is started, Kivy App is immediately attempting to run.
        To its 'on_start' event is bound registering method that
        pings back the server, which then marks the Form as
        registered. This makes the Form able to receive actions
        from server and send actions back.
        '''
        # ignore a killed manager
        # force user to create a new one
        if self.__killed:
            return

        command = [
            abspath(python),
            form.path,
            "port={}".format(self.port)
        ]
        self.__processes[form.name] = Thread(
            target=call,
            args=(command, )
        )
        self.__processes[form.name].start()
        return True

    def _register_form(self, name):
        forms = self.forms
        if name not in forms:
            raise FormManagerException(
                "The instance of a Form '{}' "
                "isn't available in the manager! "
                "Add it with manager.add_form(<instance>)."
                "".format(name)
            )
        if forms[name]['active']:
            raise FormManagerException(
                "The Form '{}' is already registered and active!"
                "".format(name)
            )
        self.__active_forms.append(name)

    def _unregister_form(self, name):
        forms = self.forms
        if name not in forms:
            return
        if name not in self.__active_forms:
            return
        self.__active_forms.remove(name)

    def request_action(self, form, action, values):
        if form not in self.forms:
            raise FormManagerException(
                "Can't request an action for a non-existing Form!"
            )
        if form not in self.queue:
            self.__queue[form] = []
        self.__queue[form].append([action, values])

    def check_queue(self, name):
        if DEBUG:
            Logger.info(
                'FormManager: check_queue enter: > {} <'
                ''.format(name)
            )

        response = {}
        # always return dict expected to be JSON
        if name not in self.queue:
            return response
        try:
            action, values = self.queue[name][0]
            response = {action: values}
        except IndexError:
            pass

        if DEBUG:
            Logger.info(
                'FormManager: check_queue exit: > {} <'
                ''.format(response)
            )
        return response

    def pop_queue(self, name):
        if name not in self.queue:
            return (
                "Couldn't pop from queue, no Form '{}' present"
                "".format(name)
            )
        self.__queue[name].pop(0)
        return True


class FormServerHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        manager = FormManager.get_manager()

        # tell the Frame we got the request
        self.send_response(200)

        # but force closing the request connection,
        # method and data structure
        self.send_header('Connection', 'close')
        self.send_header(
            'Access-Control-Allow-Methods',
            'POST'
        )

        self.send_header(
            'Access-Control-Allow-Headers',
            'Content-Type'
        )

        # read request & force unicode
        result = self.rfile.read(
            int(self.headers['Content-Length'])
        )
        try:
            result = result.encode('utf-8')  # py2
        except AttributeError:
            result = result.decode('utf-8')

        # convert to dict
        result = literal_eval(result)

        if DEBUG:
            Logger.info(
                'FormManager: do_POST enter: > {} <'
                ''.format(result)
            )

        # if the Form is added to the manager,
        # it should ping the server back
        # after running the App
        if 'register' in result:
            manager._register_form(
                result.pop('register')
            )
            message_dict = {'result': 'OK'}
        elif 'unregister' in result:
            manager._unregister_form(
                result.pop('unregister')
            )
            # Form unregistered,
            # nothing to do after that
            self.end_headers()
            return

        # add action from Form to FormManager queue
        elif 'add_action' in result:
            result = result['add_action']
            for form in result:
                if form not in self.queue:
                    self.__queue[form] = []
                self.__queue[form].append([action, values])
            message_dict = {'result': 'OK'}
        # ask action from FormManager for a specific Form
        elif 'ask_action' in result:
            message_dict = manager.check_queue(
                result['ask_action']
            )
        elif 'callback' in result:
            form = result['callback']['name']
            message_dict = {
                'queue_pop': manager.pop_queue(form)
            }
        else:
            # ignore everything not explicitly implemented
            self.end_headers()
            return

        if DEBUG:
            Logger.info(
                'FormManager: do_POST exit: > {} <'
                ''.format(message_dict)
            )
        # create a response message
        message = str(message_dict)
        if not isinstance(message, bytes):  # py3
            message = message.encode('utf-8')
        self.send_header(
            'Content-Length',
            len(message)
        )
        self.end_headers()

        # send message
        self.wfile.write(message)


class Form:
    def __init__(self, form_file, timeout=0.5):
        self.manager = FormManager.get_manager()
        self.__name, ext = split_ext(
            basename(abspath(form_file))
        )
        self.__path = abspath(form_file)

    @property
    def name(self):
        return self.__name

    @property
    def path(self):
        return self.__path


class FormApp(App):
    __ask_interval = 1 / 30.0
    __exitstatus = 1
    __symbols = {}
    __actions = {
        'pass': lambda *_, **__: None,
        'print': print,
        'setattr': setattr,

        'print_value': lambda cls, name: print(getattr(
            FormApp.__symbols[cls], name
        )),

        'call': lambda cls, name, *a, **kw: getattr(
            FormApp.__symbols[cls], name
        )(),

        'call_args': lambda cls, name, *a, **kw: getattr(
            FormApp.__symbols[cls], name
        )(a, ),

        'call_kwargs': lambda cls, name, *a, **kw: getattr(
            FormApp.__symbols[cls], name
        )(kw, ),

        'call_args_kwargs': lambda cls, name, *a, **kw: getattr(
            FormApp.__symbols[cls], name
        )(a, kw),

        'stop': lambda *_, **__: getattr(
            FormApp.__symbols['self'], 'stop'
        )()
    }

    def __init__(self, **kwargs):
        super(FormApp, self).__init__(**kwargs)
        import sys
        port_in_args = ['port=' in arg for arg in sys.argv]
        assert any(port_in_args), (
            "No PORT argument specified, one required!"
        )
        assert port_in_args.count(True) == 1, (
            "Multiple PORT arguments passed, only one required!"
        )

        FormApp._get_symbols()

        # forbid user to mess with it
        self.__port = sys.argv[port_in_args.index(True)].strip('port=')
        self.bind(on_start=self._register)
        self.bind(on_stop=self._unregister)

    def _register(self, *args):
        '''Ask to register from a FormManager via POST request.

        .. note::
            This is an automatically called private method.
        '''
        result = self.__send_json(
            host='http://127.0.0.1',
            port=self.__port,
            data={'register': self.name}
        )
        self.asking = Clock.schedule_interval(
            self._ask,
            self.__ask_interval
        )

    def _ask(self, *args):
        '''Ask for action from a FormManager via POST request.

        .. note::
            This is an automatically called private method scheduled
            after a :class:`FormApp` is registered.
        '''
        result = self.__send_json(
            host='http://127.0.0.1',
            port=self.__port,
            data={'ask_action': self.name}
        )

        status = 0
        action = None
        error = ''

        # we got something, let's stop asking to prevent duplicates
        if result:
            Clock.unschedule(self.asking)

        # allow only one action
        if len(result) > 1:
            status = 1

        # use predefined actions instead of bare 'exec'
        for key in result:
            if key not in self.__actions:
                continue
            action = key
            try:
                self.__actions[key](*result[key])
            except Exception as e:
                status = 1
                error = repr(e)

        if not action:
            # no action to execute,
            # start asking for actions again
            self.asking = Clock.schedule_interval(
                self._ask,
                self.__ask_interval
            )
            return

        if DEBUG:
            Logger.info(
                'FormManager: Form ask, got action: > {} <'
                ''.format(action)
            )

        result = self.__send_json(
            host='http://127.0.0.1',
            port=self.__port,
            data={'callback': {
                "name": self.name,
                "action": action,
                "status": status,
                "error": error
            }}
        )

        if DEBUG:
            Logger.info(
                'FormManager: Form ask, callback: > {} <'
                ''.format(result)
            )

        # require True to confirm pop from queue
        if not 'queue_pop' in result or result['queue_pop'] is not True:
            if action:
                raise FormManagerException(
                    "Action wasn't popped out of the FormManager queue!"
                )

        # everything executed properly,
        # start asking for actions again
        self.asking = Clock.schedule_interval(
            self._ask,
            self.__ask_interval
        )

    def _unregister(self, *args):
        '''Ask to register from a FormManager via POST request.

        .. note::
            This is an automatically called private method.
        '''
        # App was stopped successfully,
        # therefore exit with status 0
        self.__exitstatus = 0
        result = self.__send_json(
            host='http://127.0.0.1',
            port=self.__port,
            data={'unregister': self.name}
        )
        Clock.unschedule(self.asking)

    @classmethod
    def _get_symbols(cls):
        # override to make more classes visible to the
        # 'call' action, therefore making its attributes
        # readable and callable too
        cls.__symbols = {
            "self": FormApp.get_running_app(),
            "FormApp": FormApp
        }

    def __send_json(self, host, port, data):
        try:
            from urllib.request import Request, urlopen, URLError
        except ImportError:
            from urllib2 import Request, urlopen, URLError

        json = str(data)
        request = Request(
            host + ':' + str(port),
            bytearray(json, 'utf-8'),
            {'Content-Type': 'application/json'}
        )

        server_died = False
        try:
            json = urlopen(request).read().decode()
        except URLError as e:
            if '10061' in str(e):
                server_died = True
            else:
                raise

        # purge a long-ish Traceback from socket which basically
        # tells nothing useful except "Connection Refused"
        if server_died:
            Logger.warning(
                "FormManager: FormManager was killed, exiting!"
            )
            # must not call App.stop() here, or it locks!
            # App is here either after _unregister or after the manager
            # is dead, therefore it doesn't even make sense calling it
            exit(self.__exitstatus)

        if json == '':
            return {}
        return literal_eval(json)
