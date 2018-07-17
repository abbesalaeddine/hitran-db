import PyQt5.QtCore
from utils.log import *
from widgets.band_display_window_gui import BandDisplayWindowGui
from widgets.graph_display_window_gui import *
from worker.hapi_worker import *
from worker.work_result import WorkResult
from worker.work_request import WorkRequest
from windows.window import Window
from utils.graph_type import GraphType


class GraphDisplayWindow(Window):
    done_signal = QtCore.pyqtSignal(object)

    graph_ty_to_work_ty = {
        GraphType.ABSORPTION_COEFFICIENT: WorkRequest.ABSORPTION_COEFFICIENT,
        GraphType.TRANSMITTANCE_SPECTRUM: WorkRequest.TRANSMITTANCE_SPECTRUM,
        GraphType.RADIANCE_SPECTRUM: WorkRequest.RADIANCE_SPECTRUM,
        GraphType.ABSORPTION_SPECTRUM: WorkRequest.ABSORPTION_SPECTRUM,
        GraphType.BANDS: WorkRequest.BANDS
    }

    graph_windows = {}

    next_graph_window_id = 1

    @staticmethod
    def window_id():
        r = GraphDisplayWindow.next_graph_window_id
        GraphDisplayWindow.next_graph_window_id += 1
        return r

    def __init__(self, graph_ty, work_object, parent):
        """
        Initializes the GUI and sends a work request for the graph to be plotted, and connect 
        signals to the appropriate handler methods.

        @param ty the type of graph to be calculated. May be different for different types of graphs
        @param work_object has information about the graph that is to be made
        @param parent the parent QObject
        
        """
        self.graph_ty = graph_ty
        self.window_id = GraphDisplayWindow.window_id()
        if graph_ty in (GraphType.BANDS, GraphType.ABSORPTION_COEFFICIENT):
            gui: BandDisplayWindowGui = BandDisplayWindowGui()
            self.workers = { '0': HapiWorker(GraphDisplayWindow.graph_ty_to_work_ty[graph_ty], work_object,
                                             lambda x: [self.plot_bands(x), self.workers.pop('0')]) }
        else:
            gui: GraphDisplayWindowGui = GraphDisplayWindowGui(graph_ty, work_object['title'] + ' - ' + str(self.window_id))
            self.workers = { '0': HapiWorker(GraphDisplayWindow.graph_ty_to_work_ty[graph_ty], work_object,
                                            lambda x: [self.plot(x), self.workers.pop('0')]) }

        Window.__init__(self, gui, parent)

        # GraphDisplayWindow.graph_windows[graph_ty][self.window_id] = self

        GraphDisplayWindow.graph_windows[str(self.window_id)] = self

        self.workers['0'].start()
        self.cur_work_id = 1
        self.done_signal.connect(lambda: parent.done_graphing())
        self.gui.setWindowTitle(work_object['title'] + ' - ' + str(self.window_id))
        self.open()

    def add_worker(self, graph_ty, work_object):
        id = str(self.cur_work_id)
        self.cur_work_id += 1
        if graph_ty in (GraphType.BANDS, GraphType.ABSORPTION_COEFFICIENT):
            worker = HapiWorker(GraphDisplayWindow.graph_ty_to_work_ty[graph_ty], work_object,
                                lambda x: [self.plot_bands(x), self.workers.pop(id)])
        else:
            worker = HapiWorker(GraphDisplayWindow.graph_ty_to_work_ty[graph_ty], work_object,
                                lambda x: [self.plot(x), self.workers.pop(id)])

        self.workers[id] = worker
        worker.start()

    def close(self):
        """
        Overrides Window.close implementation, removes self from GraphDisplayWindow.graph_windows
        """
        # GraphDisplayWindow.graph_windows[graph_ty].pop(str(self.window_id), None)
        GraphDisplayWindow.graph_windows.pop(str(self.window_id), None)
        self.parent.update_existing_window_items()
        Window.close(self)

    def plot(self, work_result: WorkResult):
        """
        Plots the graph stored in 'work_result', which may be an error message rather than a result
        dictionary. If this is the case the error is printed to the console. This also emits a 'done' signal.

        @param work_result the result of the HapiWorker; it will either be a string (which indicates an error), or it
                            will be a dictionary that contains the x and y coordinates and some information about graph
                            labels
        """
        self.done_signal.emit(0)

        if type(work_result.result) != dict:
            err_log('Encountered error while graphing: ' + str(work_result.result))
            return

        try:
            result = work_result.result
            (x, y) = result['x'], result['y']
            self.gui.add_graph(x, y, result['title'], result['titlex'], result['titley'], result['name'],
                               result['args'])
        except Exception as e:
            err_log(e)

    def plot_bands(self, work_result: WorkResult):
        """
        Functions the same as `plot`, except this function is for plotting `Bands` objects
        """
        self.done_signal.emit(0)

        if type(work_result.result) != Bands:
            err_log('Encountered error while graphing: ' + str(work_result.result))
            return

        try:
            bands = work_result.result
            self.gui.add_bands(bands)
        except Exception as e:
            err_log(e)