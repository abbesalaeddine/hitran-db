from PyQt5.QtWidgets import QMainWindow, QTextEdit, QScrollArea, QAction, \
    QStatusBar

from widgets.graphing.graphing_widget import *
from widgets.molecule_info_widget import MoleculeInfoWidget
from windows.molecule_info_window import MoleculeInfoWindow
from widgets.gui import GUI

from widgets.select_widget import SelectWidget
from widgets.fetch_widget import FetchWidget
from widgets.edit_widget import EditWidget


class MainWindowGui(GUI, QMainWindow):
    """
    The main window contains most of the functionality. This includes the Edit widget, Fetch widget, Select widget, and
    graphing widget.
    """

    def __init__(self, parent):
        """
        Instantiates all of the widgets for each of the individual tabs
        """
        QMainWindow.__init__(self)
        GUI.__init__(self)

        self.parent = parent
        self.workers = []

        self.about: QTextEdit = None

        # Containers
        self.select_container: QVBoxLayout = None
        self.fetch_container: QVBoxLayout = None
        self.edit_container: QVBoxLayout = None

        # Elements in 'Molecules' tab
        self.molecule_container: QVBoxLayout = None
        self.molecules_popout_button: QPushButton = None
        self.selected_molecules: QComboBox = None
        self.molecule_info = None

        # Elements in 'Graphing' tab
        self.graphing_tab: QWidget = None
        self.graphing_container: QScrollArea = None

        # Other stuff..
        self.config_action: QAction = None
        self.statusbar: QStatusBar = None

        self.config_window = None

        # All of the gui elements get loaded and initialized by loading the ui file
        uic.loadUi('layouts/main_window.ui', self)

        self.config_action.triggered.connect(self.__on_config_action)

        self.about.setText(open('res/html/description.html', 'r').read())

        self.fetch_widget = FetchWidget(self)
        self.fetch_container.addWidget(self.fetch_widget)

        self.select_widget = SelectWidget(self)
        self.select_container.addWidget(self.select_widget)

        self.edit_widget = EditWidget(self)
        self.edit_container.addWidget(self.edit_widget)

        self.graphing_widget = GraphingWidget(self)
        self.graphing_container.setWidget(self.graphing_widget)

        self.populate_table_lists()
        self.populate_molecule_list()

        # Initially display a molecule in the molecule widget
        self.__on_molecules_current_index_changed(0)
        self.molecules_current_molecule.currentIndexChanged.connect(self.__on_molecules_current_index_changed)
        self.molecules_popout_button.clicked.connect(self.__on_molecules_popout_button)

        self.workers = []

        self.status_bar_label = QtWidgets.QLabel("Ready")
        self.statusbar.addWidget(self.status_bar_label)

        # Display the GUI since we're done configuring it
        self.show()

    def closeEvent(self, event):
        if self.config_window:
            self.config_window.close()
        QMainWindow.closeEvent(self, event)

    def remove_worker_by_jid(self, jid: int):
        """
        *Params : int jid (job id), the method terminates a worker thread based on a given job id.*
        """
        for worker in self.workers:
            if worker.job_id == jid:
                worker.safe_exit()
                break

    def __on_config_action(self, *args):
        self.config_window = ConfigEditorWidget()
        self.config_window.show()

    def __on_molecules_current_index_changed(self, _index):
        if self.molecule_info != None:
            self.molecule_container.removeWidget(self.molecule_info)
        self.molecule_info = MoleculeInfoWidget(self.molecules_current_molecule.currentText())
        self.molecule_container.addWidget(self.molecule_info)

    def __on_molecules_popout_button(self):
        new_window: MoleculeInfoWindow = MoleculeInfoWindow(self.parent, self.molecules_current_molecule.currentText())
        new_window.gui.show()
        self.parent.add_child_window(new_window)

    def populate_molecule_list(self):
        """
        *Extract the name of each molocule that hapi has data on and add it to the molecule list. Also, enable auto-complete for the combobox.*
        """
        # our list of molecule names in the gui
        for molecule_id, _ in Isotopologue.molecules.items():
            if molecule_id >= 1000:
                continue
            molecule = Isotopologue.from_molecule_id(molecule_id)
        self.molecules_current_molecule.addItems(list(set(get_all_json_molecule_names())))

    def populate_table_lists(self, data_names=None):
        """
        *This method initializes the default table values for the fetch tab and the edit tab.*
        """
        if data_names == None:
            data_names = get_all_data_names()
        self.edit_widget.table_name.clear()
        self.edit_widget.table_name.addItems(data_names)
        self.select_widget.table_name.clear()
        self.select_widget.table_name.addItems(data_names)
        self.graphing_widget.data_name.clear()
        self.graphing_widget.data_name.addItems(data_names)
