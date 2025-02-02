import functools
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union

from data_structures.bands import Band, Bands
from data_structures.xsc import CrossSection
from hapi import *
from metadata.config import Config
from metadata.hapi_metadata import HapiMetaData
from utils.fetch_error import FetchError, FetchErrorKind
from utils.hapi_api import CrossSectionApi
from utils.hapiest_util import echo
from utils.log import *


LOCAL_XSC_CACHE: Dict[str, CrossSection] = {
    #    'MOLECULE_PARAMATERS.xsc': { # Keep the .xsc extension on the name
    #        'nu': [1, 2, 3],
    #        'abscoef': [4, 5, 6],
    #        'numin': 1,
    #        'numax: 3
    #    },
    }


def add_xsc_to_cache(name, text=None):
    """
    Adds a cross section to the in memory cache.
    :param name: The name of the file. This should not be a path, just the filename.
    :param text: If this cross section hasn't been written to the filesystem yet, specify the
    file text here, and it
                will be written to a file.
    :return: Returns True if it was added to the cache successfully, False otherwise.
    """
    from data_structures.xsc import XscParser

    if type(text) == bytes:
        text = text.decode('utf-8')
    try:
        if text is None:
            with open(os.path.join(Config.data_folder, name), 'r') as file:
                text = file.read()
        else:
            with open(os.path.join(Config.data_folder, name), 'w+') as file:
                file.write(text)
    except Exception as e:
        print(f"Failed to add xsc to in memory cache: {str(e)}")
        return False

    LOCAL_XSC_CACHE[name] = XscParser.parse(text)
    return True


class WorkFunctions:
    @staticmethod
    def start_hapi(**_kwargs) -> bool:
        """
        Initilizes the hapi database (i.e. loads all data into RAM).
        """
        print('Initializing hapi db...')
        try:
            db_begin(Config.data_folder)
            del LOCAL_TABLE_CACHE['sampletab']
            print('Done initializing hapi db...')
        except Exception as e:
            print('Error initializing hapi db...' + str(e))
            traceback.print_exc()
            return False

        # All file names in the data folder
        all_files = os.listdir(Config.data_folder)
        # Create a HMD file for every table that doesn't have one.
        for key, table in LOCAL_TABLE_CACHE.items():
            if (str(key) + ".hmd") not in all_files and not key.endswith(".xsc"):
                hmd = HapiMetaData(key)
                hmd.initialize_from_hapi_table(key)
                hmd.save()
        for filename in os.listdir(Config.data_folder):
            if filename.endswith('.xsc'):
                add_xsc_to_cache(filename)

        return True

    graph_type_map = {
        "Voigt":    absorptionCoefficient_Voigt,
        "Lorentz":  absorptionCoefficient_Lorentz,
        "Gauss":    absorptionCoefficient_Gauss,
        "SD Voigt": absorptionCoefficient_SDVoigt,
        "Galatry":  absorptionCoefficient_Doppler,
        "HT":       absorptionCoefficient_HT
        }

    instrumental_fn_map = {
        "rectangular": SLIT_RECTANGULAR,
        "triangular":  SLIT_TRIANGULAR,
        "gaussian":    SLIT_GAUSSIAN,
        "diffraction": SLIT_DIFFRACTION,
        "michelson":   SLIT_MICHELSON,
        "dispersion":  SLIT_DISPERSION
        }

    @staticmethod
    def graph_bands(TableName: str, **_kwargs) -> Bands:
        """
        The following set of local functions were supplied by R.V. Kochanov, modified /
        refactored by Joshua Karns.
        The process every line in a table and separate the bands (i.e. groups together bands that
        have the same lower
        and upper quanta.
        :returns: the bands for the table!
        """

        def make_band_index():
            """
            Create the band index.
            Band index is a dictionary of the format:
                DICT[BAND] = IDS,
                where BAND = (global_upper_quanta,global_lower_quanta)   (i.e. a tuple consisting
                from two parameters)
                IDS = indexes of the lines in LOCAL_TABLE_HASH corresponding to the BAND
            """
            data = LOCAL_TABLE_CACHE[TableName]['data']
            band2index = { }

            def process_band(params):
                """
                params should be a 3-tuple that contains (global_upper_quanta,
                global_lower_quanta, index)
                """
                band2index.setdefault((params[0], params[1]), []).append(params[2])

            quanta_with_index = zip(data['global_upper_quanta'], data['global_lower_quanta'],
                                    range(0, len(data['global_lower_quanta'])))
            list(map(process_band, quanta_with_index))

            return band2index

        def get_parameters(ids, params=('nu', 'sw')):
            """
            Get line parameters as a columns from the LOCAL_TABLE_HASH
            using the ID numbers. Parameter names are specified in PARS.
            """
            data = LOCAL_TABLE_CACHE[TableName]['data']
            return zip(*list(map(lambda id: list(map(lambda par: data[par][id], params)), ids)))

        band2index = make_band_index()

        def get_band(band) -> Band:
            ids = band2index[band]
            nu, sw = get_parameters(ids)
            return Band(nu, sw, "{} _ {}".format(band[0].strip(), band[1].strip()))

        return Bands(list(map(get_band, band2index.keys())), TableName)

    @staticmethod
    def convolve_spectrum(x, y, instrumental_fn: str, Resolution: float, AF_wing: float):
        """
        Applies an instrumental function to (x, y) coordinates if one was selected.
        
        :returns: the original (x, y) coordinates if no instrumental function was selected,
                otherwise it applies it and returns the result.
        """
        instrumental_fn = instrumental_fn.lower()
        if instrumental_fn not in WorkFunctions.instrumental_fn_map:
            return x, y
        else:
            newx, newy, i, j, slit = convolveSpectrum(x, y, Resolution = Resolution,
                                                      AF_wing = AF_wing,
                                                      SlitFunction =
                                                      WorkFunctions.instrumental_fn_map[
                                                          instrumental_fn])
            return newx, newy

    @staticmethod
    def graph_absorption_coefficient(
            graph_fn: str, Components: List[Tuple[int, int]], SourceTables: List[str],
            Environment: Dict[str, Any], Diluent: dict, WavenumberRange: Tuple[float, float],
            WavenumberStep: float, WavenumberWing: float, WavenumberWingHW: float, title: str,
            titlex: str, titley: str,
            **kwargs) -> Dict[str, Union[str, Any]]:
        """
        :param graph_fn:        Name of the graphing function to be applied.
        :param Components:      Which (mol_id, isotopologue_id) pairs will be found in the table
        :param SourceTables:    A list which (should) only contains one element.
        :param Environment:     Temperature and pressure information.
        :param Diluent:         Mixing ratio of air / substace
        :param WavenumberRange: Min and max wavenumber
        :param WavenumberStep:  How much the wavenumber increases per step
        :param WavenumberWing:  Not sure
        :param WavenumberWingHW: Note sure
        :param title:           Title of the graph
        :param titlex:          Title for the x axis
        :param titley:          Title for the y axis
        :param kwargs:         Unused keyword-arguments
        :return:
        """
        name = kwargs['name']
        kwargs = {
            'WavenumberRange': WavenumberRange, 'Environment': Environment, 'graph_fn': graph_fn,
            'Diluent':         Diluent
        }
        if SourceTables[0] in LOCAL_XSC_CACHE:
            xsc = LOCAL_XSC_CACHE[SourceTables[0]]
            return {
                'x':      xsc.nu, 'y': xsc.abscoef, 'title': title, 'titlex': titlex,
                'titley': titley,
                'name': name,
                'args': {'xsc': True, **kwargs}
            }

        # absorptionCoefficient_Doppler functions do not use Diluent
        if WorkFunctions.graph_type_map[graph_fn] == WorkFunctions.graph_type_map["Galatry"]:
            x, y = WorkFunctions.graph_type_map[graph_fn](
                    Components = Components,
                    SourceTables = SourceTables,
                    Environment = Environment,
                    HITRAN_units = False,
                    WavenumberRange = WavenumberRange,
                    WavenumberStep = WavenumberStep,
                    WavenumberWing = WavenumberWing,
                    WavenumberWingHW = WavenumberWingHW)
        else:
            x, y = WorkFunctions.graph_type_map[graph_fn](
                    Components = Components,
                    SourceTables = SourceTables,
                    Environment = Environment,
                    Diluent = Diluent,
                    HITRAN_units = False,
                    WavenumberRange = WavenumberRange,
                    WavenumberStep = WavenumberStep,
                    WavenumberWing = WavenumberWing,
                    WavenumberWingHW = WavenumberWingHW)

        return {
            'x':      x,
            'y':      y,
            'title':  title,
            'titlex': titlex,
            'titley': titley,
            'name':   name,
            'args':   { 'xsc': False, **kwargs }
            }

    @staticmethod
    def graph_absorption_spectrum(
            graph_fn: str, Components: List[Tuple[int, int]], SourceTables: List[str],
            Environment: Dict[str, Any], Diluent: dict, WavenumberRange: Tuple[float, float],
            WavenumberStep: float, WavenumberWing: float, WavenumberWingHW: float, title: str,
            titlex: str, titley: str,
            Format='%e %e', path_length=100.0, File=None, instrumental_fn: str = "",
            Resolution: float = 0.01, AF_wing: float = 100.0, **kwargs) -> Union[
        Dict[str, Any], Exception]:
        """
        Generates coordinates for absorption spectrum graph.
        """
        name = kwargs['name']
        kwargs = {
            'WavenumberRange': WavenumberRange, 'Environment': Environment, 'graph_fn': graph_fn,
            'Diluent':         Diluent
        }
        wn, ac = WorkFunctions.graph_type_map[graph_fn](
                Components = Components,
                SourceTables = SourceTables,
                Environment = Environment,
                Diluent = Diluent,
                HITRAN_units = False,
                WavenumberRange = WavenumberRange,
                WavenumberStep = WavenumberStep,
                WavenumberWing = WavenumberWing,
                WavenumberWingHW = WavenumberWingHW)
        Environment = { 'l': path_length }
        x, y = absorptionSpectrum(wn, ac, Environment = Environment, File = File, Format = Format)
        rx, ry = WorkFunctions.convolve_spectrum(x, y, instrumental_fn, Resolution = Resolution,
                                                 AF_wing = AF_wing)
        return {
            'x':      rx, 'y': ry, 'title': title, 'name': name, 'titlex': titlex,
            'titley': titley, 'args': kwargs
        }

    @staticmethod
    def graph_radiance_spectrum(
            graph_fn: str, Components: List[Tuple[int, int]], SourceTables: List[str],
            Environment: Dict[str, Any], Diluent: dict, HITRAN_units: bool,
            WavenumberRange: Tuple[float, float],
            WavenumberStep: float, WavenumberWing: float, WavenumberWingHW: float, title: str,
            titlex: str, titley: str,
            Format='%e %e', path_length=100.0, temp=296.0, File=None, instrumental_fn: str = "",
            Resolution: float = 0.01, AF_wing: float = 100.0, **kwargs) -> Union[
        Dict[str, Any], Exception]:
        """
        Generates coordinates for radiance spectrum graph.
        """
        name = kwargs['name']
        kwargs = {
            'WavenumberRange': WavenumberRange, 'Environment': Environment, 'graph_fn': graph_fn,
            'Diluent':         Diluent
        }
        wn, ac = WorkFunctions.graph_type_map[graph_fn](
                Components = Components,
                SourceTables = SourceTables,
                Environment = Environment,
                Diluent = Diluent,
                HITRAN_units = False,
                WavenumberRange = WavenumberRange,
                WavenumberStep = WavenumberStep,
                WavenumberWing = WavenumberWing,
                WavenumberWingHW = WavenumberWingHW)
        Environment['l'] = path_length
        x, y = radianceSpectrum(wn, ac, Environment = Environment, File = File, Format = Format)
        rx, ry = WorkFunctions.convolve_spectrum(x, y, instrumental_fn, Resolution = Resolution,
                                                 AF_wing = AF_wing)
        return {
            'x':      rx, 'y': ry, 'title': title, 'name': name, 'titlex': titlex,
            'titley': titley, 'args': kwargs
        }

    @staticmethod
    def graph_transmittance_spectrum(
            graph_fn: str, Components: List[Tuple[int, int]], SourceTables: List[str],
            Environment: Dict[str, Any], Diluent: dict, HITRAN_units: bool,
            WavenumberRange: Tuple[float, float],
            WavenumberStep: float, WavenumberWing: float, WavenumberWingHW: float, title: str,
            titlex: str, titley: str,
            Format='%e %e', path_length=100.0, File=None, instrumental_fn: str = "",
            Resolution: float = 0.01, AF_wing: float = 100.0, **kwargs) -> Union[
        Dict[str, Any], Exception]:
        """
        Generates coordinates for transmittance spectrum graph.
        """
        name = kwargs['name']
        kwargs = {
            'WavenumberRange': WavenumberRange, 'Environment': Environment, 'graph_fn': graph_fn,
            'Diluent':         Diluent
        }
        wn, ac = WorkFunctions.graph_type_map[graph_fn](
                Components = Components,
                SourceTables = SourceTables,
                Environment = Environment,
                Diluent = Diluent,
                HITRAN_units = False,
                WavenumberRange = WavenumberRange,
                WavenumberStep = WavenumberStep,
                WavenumberWing = WavenumberWing,
                WavenumberWingHW = WavenumberWingHW)
        Environment = { 'l': path_length }
        x, y = transmittanceSpectrum(wn, ac, Environment = Environment, File = File,
                                     Format = Format)
        rx, ry = WorkFunctions.convolve_spectrum(x, y, instrumental_fn, Resolution = Resolution,
                                                 AF_wing = AF_wing)
        return {
            'x':      rx, 'y': ry, 'title': title, 'name': name, 'titlex': titlex,
            'titley': titley, 'args': kwargs
        }

    @staticmethod
    def fetch(data_name: str, iso_id_list: List[int], numin: float, numax: float,
              parameter_groups: List[str] = (), parameters: List[str] = (), **_kwargs) -> Union[
        Dict[str, List[str]], 'FetchError']:
        """
        Method handles verification of user input for fetch function.
        """
        if len(iso_id_list) == 0:
            return FetchError(FetchErrorKind.BadIsoList,
                              'Fetch Failure: Iso list cannot be empty.')
        try:
            fetch_by_ids(data_name, iso_id_list, numin, numax, parameter_groups, parameters)
            hmd = HapiMetaData(data_name, iso_id_list, numin, numax)
        except Exception as e:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            traceback.print_tb(exc_traceback)
            debug('Fetch error: ', e)
            as_str = str(e)
            # Determine whether the issue is an internet issue or something else
            if 'connect' in as_str:
                return FetchError(
                        FetchErrorKind.BadConnection,
                        'Bad connection: Failed to connect to send request. Check your connection.')
            else:
                return FetchError(
                        FetchErrorKind.FailedToRetrieveData,
                        'Fetch failure: Failed to fetch data (connected successfully, received '
                        'HTTP error as response)')

        return { 'all_tables': WorkFunctions.get_all_table_names() }

    @staticmethod
    def get_table(table_name: str) -> Optional[Dict[str, Any]]:
        if table_name in LOCAL_TABLE_CACHE:
            return LOCAL_TABLE_CACHE[table_name]
        else:
            return None

    @staticmethod
    def save_table(table: Dict[str, Any], name: str, **_kwargs):
        """
        Saves the modified table in the local table cache and on disk.
        """
        try:
            # This also means the files already exist on disk and do not need to be created
            if name in LOCAL_TABLE_CACHE:
                del LOCAL_TABLE_CACHE[name]
            else:
                open(Config.data_folder + "/{}.header".format(name), 'w+')
                open(Config.data_folder + "/{}.data".format(name), 'w+')

            LOCAL_TABLE_CACHE[name] = table
            # Cahce2storage requires that the '{tablename}.par' and '{tablename}.header' files exist
            cache2storage(TableName = name)
            return True
        except Exception as e:
            print(str(e))
            return False

    @staticmethod
    def get_all_table_names() -> List[str]:
        l = list(tableList())
        return l + list(LOCAL_XSC_CACHE.keys())

    @staticmethod
    def table_meta_data(table_name: str):
        """
        Initilizes meta data file.
        """
        if table_name == None or table_name == '':
            return None

        # The header is only used for normal tables, not cross sections
        header = None
        if table_name in LOCAL_XSC_CACHE:
            xsc = LOCAL_XSC_CACHE[table_name]
            numin = xsc.numin
            numax = xsc.numax
            length = xsc.len
            parameters = []
        else:
            table = LOCAL_TABLE_CACHE[table_name]['data']
            header = LOCAL_TABLE_CACHE[table_name]['header']
            parameters = list(table.keys())
            numin = min(LOCAL_TABLE_CACHE[table_name]['data']['nu'])
            numax = max(LOCAL_TABLE_CACHE[table_name]['data']['nu'])
            length = header['number_of_rows']
            xsc = None
        return echo(length = length, header = header, parameters = parameters, numin = numin,
                    numax = numax, xsc = xsc)

    @staticmethod
    def table_names(**_kwargs):
        """
        Returns all table names in local cache.
        """
        return WorkFunctions.get_all_table_names()

    @staticmethod
    def select(TableName: str, DestinationTableName: str = QUERY_BUFFER,
               ParameterNames: List[str] = None,
               Conditions: List[Any] = None, Output: bool = False, File=None, **_kwargs):
        """
        Attempts to call the select() method from hapi.
        """
        select(TableName = TableName, DestinationTableName = DestinationTableName,
               ParameterNames = ParameterNames,
               Conditions = Conditions, Output = Output, File = File)
        hmd = HapiMetaData(DestinationTableName)
        WorkFunctions.save_table(LOCAL_TABLE_CACHE[TableName], table_name = DestinationTableName)

        return echo(new_table_name = DestinationTableName, all_tables = list(tableList()))

    @staticmethod
    def download_xscs(xscs: List[str], molecule_name: str, **_kwargs):
        api = CrossSectionApi()
        for xsc_name in xscs:
            split = molecule_name.split('_')
            if len(split) <= 1:
                filename = xsc_name
            else:
                split[0] = molecule_name
                filename = functools.reduce(str.__add__, split)
            res: bytes = api.request_xsc(xsc_name, filename)
            if res is None:
                return None
            else:
                if not add_xsc_to_cache(filename, res):
                    return None
        return True
