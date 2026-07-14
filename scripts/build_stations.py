#!/usr/bin/env python3
"""Build data/stations.json: curated station vocabulary plus per-page label coordinates.

The station table below was curated from the PDF text layer of all four pages.
Obvious extraction garbles are fixed in the canonical name and flagged suspect
so the page agents verify them against the rendered image. Coordinates come
from matching each entry's printed label text against the per-page word list.

Usage:
    uv run --with pymupdf scripts/build_stations.py
"""

import json
import re
import unicodedata
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "spoorkaart2026.pdf"
OUT = ROOT / "data" / "stations.json"
SOURCE = "spoorkaart2026.pdf versie 26.02 (oktober 2025)"

# Entry: (canonical name, printed search key, country, flags, id override, hit picker)
# flags: M = major (boxed label on the map), S = suspect (verify name on the image)
# hit picker: min_y / max_y, used when the same label text appears more than once
E = lambda name, key, country, flags="", ident=None, picker=None: (
    name, key, country, flags, ident, picker
)

STATIONS = [
    # Noord-Holland
    E("Den Helder", "Den Helder", "NL"),
    E("Den Helder Zuid", "Den Helder Zuid", "NL"),
    E("Anna Paulowna", "Anna Paulowna", "NL"),
    E("Schagen", "Schagen", "NL"),
    E("Heerhugowaard", "Heerhugowaard", "NL"),
    E("Alkmaar Noord", "Alkmaar Noord", "NL"),
    E("Alkmaar", "Alkmaar", "NL", "M"),
    E("Heiloo", "Heiloo", "NL"),
    E("Castricum", "Castricum", "NL"),
    E("Uitgeest", "Uitgeest", "NL"),
    E("Heemskerk", "Heemskerk", "NL"),
    E("Beverwijk", "Beverwijk", "NL"),
    E("Driehuis", "Driehuis", "NL"),
    E("Santpoort Noord", "Santpoort Noord", "NL"),
    E("Santpoort Zuid", "Santpoort Zuid", "NL"),
    E("Bloemendaal", "Bloemendaal", "NL"),
    E("Overveen", "Overveen", "NL"),
    E("Haarlem", "Haarlem", "NL", "M"),
    E("Haarlem Spaarnwoude", "Haarlem Spaarnwoude", "NL"),
    E("Zandvoort aan Zee", "Zandvoort aan Zee", "NL"),
    E("Heemstede-Aerdenhout", "Aerdenhout", "NL"),
    E("Obdam", "Obdam", "NL"),
    E("Hoorn", "Hoorn", "NL", "M"),
    E("Hoorn Kersenboogerd", "Hoorn Kersenboogerd", "NL"),
    E("Hoogkarspel", "Hoogkarspel", "NL"),
    E("Bovenkarspel-Grootebroek", "Grootebroek", "NL"),
    E("Bovenkarspel Flora", "Bovenkarspel Flora", "NL"),
    E("Enkhuizen", "Enkhuizen", "NL"),
    E("Purmerend", "Purmerend", "NL"),
    E("Purmerend Overwhere", "Purmerend Overwhere", "NL"),
    E("Purmerend Weidevenne", "Purmerend Weidevenne", "NL"),
    E("Zaandam", "Zaandam", "NL"),
    E("Zaandam Kogerveld", "Zaandam Kogerveld", "NL"),
    E("Koog aan de Zaan", "Koog a/d Zaan", "NL"),
    E("Zaandijk Zaanse Schans", "Zaandijk", "NL"),
    E("Wormerveer", "Wormerveer", "NL"),
    E("Krommenie-Assendelft", "Assendelft", "NL"),
    E("Halfweg-Zwanenburg", "Zwanenburg", "NL"),
    E("Hoofddorp", "Hoofddorp", "NL"),
    E("Nieuw Vennep", "Nieuw Vennep", "NL"),
    E("Schiphol Airport", "Schiphol Airport", "NL", "M"),
    E("Amsterdam Centraal", "Amsterdam Centraal", "NL", "M"),
    E("Amsterdam Sloterdijk", "A'dam Sloterdijk", "NL", "M"),
    E("Amsterdam Lelylaan", "Amsterdam Lelylaan", "NL"),
    E("Amsterdam Zuid", "A'dam Zuid", "NL", "M"),
    E("Amsterdam RAI", "RAI", "NL"),
    E("Amsterdam Amstel", "Amstel", "NL"),
    E("Amsterdam Muiderpoort", "Amsterdam Muiderpoort", "NL"),
    E("Amsterdam Science Park", "Amsterdam Science Park", "NL"),
    E("Amsterdam Bijlmer ArenA", "Amsterdam Bijlmer ArenA", "NL"),
    E("Amsterdam Holendrecht", "Holendrecht", "NL"),
    E("Duivendrecht", "Duivendrecht", "NL"),
    E("Diemen", "Diemen", "NL"),
    E("Diemen Zuid", "Diemen Zuid", "NL"),
    E("Abcoude", "Abcoude", "NL"),
    # Flevoland en Gooi
    E("Weesp", "Weesp", "NL"),
    E("Almere Poort", "Almere Poort", "NL"),
    E("Almere Muziekwijk", "Almere Muziekwijk", "NL"),
    E("Almere Centrum", "Almere Centrum", "NL", "M"),
    E("Almere Parkwijk", "Almere Parkwijk", "NL"),
    E("Almere Buiten", "Almere Buiten", "NL"),
    E("Almere Oostvaarders", "Almere Oostvaarders", "NL"),
    E("Lelystad Centrum", "Lelystad Centrum", "NL"),
    E("Naarden-Bussum", "Naarden- Bussum", "NL"),
    E("Bussum Zuid", "Bussum Zuid", "NL"),
    E("Hilversum Media Park", "Hilversum Media Park", "NL"),
    E("Hilversum", "Hilversum", "NL", "M"),
    E("Hilversum Sportpark", "Hilversum Sportpark", "NL"),
    E("Baarn", "Baarn", "NL"),
    E("Soest", "Soest", "NL"),
    E("Soestdijk", "Soestdijk", "NL"),
    E("Soest Zuid", "Soest Zuid", "NL"),
    E("Den Dolder", "Den Dolder", "NL"),
    E("Bilthoven", "Bilthoven", "NL"),
    E("Hollandsche Rading", "Hollandsche Rading", "NL"),
    # Utrecht
    E("Utrecht Centraal", "Utrecht Centraal", "NL", "M"),
    E("Utrecht Overvecht", "Overvecht", "NL"),
    E("Utrecht Zuilen", "Zuilen", "NL"),
    E("Maarssen", "Maarssen", "NL"),
    E("Breukelen", "Breukelen", "NL"),
    E("Utrecht Leidsche Rijn", "Leidsche Rijn", "NL"),
    E("Utrecht Terwijde", "Terwijde", "NL"),
    E("Vleuten", "Vleuten", "NL"),
    E("Utrecht Vaartsche Rijn", "Vaartsche Rijn", "NL"),
    E("Utrecht Lunetten", "Utrecht Lunetten", "NL"),
    E("Utrecht Maliebaan", "Utrecht Maliebaan", "NL"),
    E("Bunnik", "Bunnik", "NL"),
    E("Driebergen-Zeist", "Driebergen- Zeist", "NL"),
    E("Maarn", "Maarn", "NL"),
    E("Veenendaal West", "Veenendaal West", "NL"),
    E("Veenendaal Centrum", "Veenendaal Centrum", "NL"),
    E("Veenendaal-De Klomp", "de Klomp", "NL"),
    E("Rhenen", "Rhenen", "NL"),
    E("Houten", "Houten", "NL"),
    E("Houten Castellum", "Houten Castellum", "NL"),
    E("Culemborg", "Culemborg", "NL"),
    E("Geldermalsen", "Geldermalsen", "NL"),
    E("Zaltbommel", "Zaltbommel", "NL"),
    E("Beesd", "Beesd", "NL"),
    E("Leerdam", "Leerdam", "NL"),
    E("Arkel", "Arkel", "NL"),
    E("Gorinchem", "Gorinchem", "NL"),
    # Zuid-Holland
    E("Leiden Centraal", "Leiden Centraal", "NL", "M"),
    E("Leiden Lammenschans", "Lammenschans", "NL"),
    E("De Vink", "De Vink", "NL"),
    E("Voorschoten", "Voorschoten", "NL"),
    E("Voorhout", "Voorhout", "NL"),
    E("Sassenheim", "Sassenheim", "NL"),
    E("Hillegom", "Hillegom", "NL"),
    E("Den Haag Centraal", "Den Haag Centraal", "NL", "M"),
    E("Den Haag HS", "Den Haag HS", "NL", "M"),
    E("Den Haag Laan van NOI", "Laan van NOI", "NL"),
    E("Den Haag Mariahoeve", "Mariahoeve", "NL"),
    E("Den Haag Moerwijk", "Moerwijk", "NL"),
    E("Den Haag Ypenburg", "Ypenburg", "NL"),
    E("Voorburg", "Voorburg", "NL"),
    E("Rijswijk", "Rijswijk", "NL"),
    E("Delft", "Delft", "NL"),
    E("Delft Campus", "Delft Campus", "NL"),
    E("Schiedam Centrum", "Schiedam Centrum", "NL"),
    E("Rotterdam Centraal", "Rotterdam Centraal", "NL", "M"),
    E("Rotterdam Noord", "Rotterdam Noord", "NL"),
    E("Rotterdam Alexander", "Rotterdam Alexander", "NL"),
    E("Rotterdam Blaak", "Rotterdam Blaak", "NL"),
    E("Rotterdam Zuid", "Rotterdam Zuid", "NL"),
    E("Rotterdam Lombardijen", "Lombardijen", "NL"),
    E("Capelle Schollevaar", "Capelle Schollevaar", "NL"),
    E("Nieuwerkerk aan den IJssel", "Nieuwerkerk a/d IJssel", "NL"),
    E("Barendrecht", "Barendrecht", "NL"),
    E("Zwijndrecht", "Zwijndrecht", "NL"),
    E("Dordrecht", "Dordrecht", "NL", "M"),
    E("Dordrecht Zuid", "Dordrecht Zuid", "NL"),
    E("Dordrecht Stadspolders", "Dordrecht Stadspolders", "NL"),
    E("Sliedrecht Baanhoek", "Baanhoek", "NL"),
    E("Sliedrecht", "Sliedrecht", "NL"),
    E("Hardinxveld Blauwe Zoom", "Blauwe Zoom", "NL"),
    E("Hardinxveld-Giessendam", "Giessendam", "NL"),
    E("Boven-Hardinxveld", "Boven-Hardinxveld", "NL"),
    E("Zoetermeer", "Zoetermeer", "NL"),
    E("Zoetermeer Oost", "Zoetermeer Oost", "NL"),
    E("Lansingerland-Zoetermeer", "Lansingerland-", "NL"),
    E("Gouda", "Gouda", "NL", "M"),
    E("Gouda Goverwelle", "Goverwelle", "NL"),
    E("Woerden", "Woerden", "NL"),
    E("Bodegraven", "Bodegraven", "NL"),
    E("Alphen aan den Rijn", "Alphen a/d Rijn", "NL"),
    E("Waddinxveen", "Waddinxveen", "NL"),
    E("Waddinxveen Noord", "Waddinxveen Noord", "NL"),
    E("Waddinxveen Triangel", "Waddinxveen Triangel", "NL"),
    E("Boskoop", "Boskoop", "NL"),
    E("Boskoop Snijdelwijk", "Boskoop Snijdelwijk", "NL"),
    # Zeeland en West-Brabant
    E("Lage Zwaluwe", "Lage Zwaluwe", "NL"),
    E("Zevenbergen", "Zevenbergen", "NL"),
    E("Oudenbosch", "Oudenbosch", "NL"),
    E("Etten-Leur", "Etten-Leur", "NL"),
    E("Roosendaal", "Roosendaal", "NL", "M"),
    E("Bergen op Zoom", "Bergen op Zoom", "NL"),
    E("Rilland-Bath", "Rilland-Bath", "NL"),
    E("Krabbendijke", "Krabbendijke", "NL"),
    E("Kruiningen-Yerseke", "Kruiningen-Yerseke", "NL"),
    E("Kapelle-Biezelinge", "Kapelle-Biezelinge", "NL"),
    E("Goes", "Goes", "NL"),
    E("Arnemuiden", "Arnemuiden", "NL"),
    E("Middelburg", "Middelburg", "NL"),
    E("Vlissingen Souburg", "Vlissingen Souburg", "NL"),
    E("Vlissingen", "Vlissingen", "NL", "M"),
    # Brabant
    E("Breda", "Breda", "NL", "M"),
    E("Breda Prinsenbeek", "Prinsenbeek", "NL"),
    E("Gilze-Rijen", "Gilze-Rijen", "NL"),
    E("Tilburg Reeshof", "Tilburg Reeshof", "NL"),
    E("Tilburg Universiteit", "Tilburg Universiteit", "NL"),
    E("Tilburg", "Tilburg", "NL", "M"),
    E("Oisterwijk", "Oisterwijk", "NL"),
    E("Boxtel", "Boxtel", "NL"),
    E("Best", "Best", "NL"),
    E("Vught", "Vught", "NL"),
    E("'s-Hertogenbosch", "Hertogenbosch", "NL", "M"),
    E("'s-Hertogenbosch Oost", "Hertogenbosch Oost", "NL"),
    E("Rosmalen", "Rosmalen", "NL"),
    E("Oss West", "Oss West", "NL"),
    E("Oss", "Oss", "NL"),
    E("Ravenstein", "Ravenstein", "NL"),
    E("Wijchen", "Wijchen", "NL"),
    E("Eindhoven Strijp-S", "Strijp-S", "NL"),
    E("Eindhoven Centraal", "Eindhoven Centraal", "NL", "M"),
    E("Geldrop", "Geldrop", "NL"),
    E("Heeze", "Heeze", "NL"),
    E("Maarheeze", "Maarheeze", "NL"),
    E("Helmond Brandevoort", "Helmond Brandevoort", "NL"),
    E("Helmond 't Hout", "Helmond 't Hout", "NL"),
    E("Helmond", "Helmond", "NL"),
    E("Helmond Brouwhuis", "Helmond Brouwhuis", "NL"),
    E("Deurne", "Deurne", "NL"),
    # Limburg
    E("Weert", "Weert", "NL"),
    E("Roermond", "Roermond", "NL", "M"),
    E("Swalmen", "Swalmen", "NL"),
    E("Reuver", "Reuver", "NL"),
    E("Tegelen", "Tegelen", "NL"),
    E("Venlo", "Venlo", "NL", "M"),
    E("Blerick", "Blerick", "NL"),
    E("Horst-Sevenum", "Sevenum", "NL"),
    E("Venray", "Venray", "NL"),
    E("Vierlingsbeek", "Vierlingsbeek", "NL"),
    E("Boxmeer", "Boxmeer", "NL"),
    E("Cuijk", "Cuijk", "NL"),
    E("Mook Molenhoek", "Mook Molenhoek", "NL"),
    E("Sittard", "Sittard", "NL", "M"),
    E("Susteren", "Susteren", "NL"),
    E("Echt", "Echt", "NL"),
    E("Geleen Oost", "Geleen Oost", "NL"),
    E("Geleen-Lutterade", "Geleen-Lutterade", "NL"),
    E("Spaubeek", "Spaubeek", "NL"),
    E("Schinnen", "Schinnen", "NL"),
    E("Nuth", "Nuth", "NL"),
    E("Hoensbroek", "Hoensbroek", "NL"),
    E("Heerlen", "Heerlen", "NL", "M"),
    E("Heerlen Woonboulevard", "Heerlen Woonblvd", "NL"),
    E("Landgraaf", "Landgraaf", "NL"),
    E("Eygelshoven", "Eygelshoven", "NL"),
    E("Eygelshoven Markt", "Eygelshoven Markt", "NL"),
    E("Chevremont", "Chevremont", "NL"),
    E("Kerkrade Centrum", "Kerkrade", "NL"),
    E("Voerendaal", "Voerendaal", "NL"),
    E("Klimmen-Ransdaal", "Klimmen-Ransdaal", "NL"),
    E("Schin op Geul", "Schin Op Geul", "NL"),
    E("Valkenburg", "Valkenburg", "NL"),
    E("Houthem-Sint Gerlach", "Houthem", "NL"),
    E("Meerssen", "Meerssen", "NL"),
    E("Bunde", "Bunde", "NL", "", None, "max_y"),
    E("Beek-Elsloo", "Beek-Elsloo", "NL"),
    E("Maastricht Noord", "Maastricht Noord", "NL"),
    E("Maastricht", "Maastricht", "NL", "M"),
    E("Maastricht Randwyck", "Maastricht Randwyck", "NL"),
    E("Eijsden", "Eijsden", "NL"),
    # Gelderland
    E("Nijmegen", "Nijmegen", "NL", "M"),
    E("Nijmegen Dukenburg", "Nijmegen Dukenburg", "NL"),
    E("Nijmegen Heyendaal", "Nijmegen Heyendaal", "NL"),
    E("Nijmegen Lent", "Nijmegen Lent", "NL"),
    E("Nijmegen Goffert", "Nijmegen Goffert", "NL"),
    E("Elst", "Elst", "NL"),
    E("Arnhem Centraal", "Arnhem Centraal", "NL", "M"),
    E("Arnhem Zuid", "Arnhem Zuid", "NL"),
    E("Arnhem Velperpoort", "Arnhem Velperpoort", "NL"),
    E("Arnhem Presikhaaf", "Arnhem Presikhaaf", "NL"),
    E("Velp", "Velp", "NL"),
    E("Rheden", "Rheden", "NL"),
    E("Dieren", "Dieren", "NL"),
    E("Brummen", "Brummen", "NL"),
    E("Zutphen", "Zutphen", "NL", "M"),
    E("Westervoort", "Westervoort", "NL"),
    E("Duiven", "Duiven", "NL"),
    E("Zevenaar", "Zevenaar", "NL"),
    E("Didam", "Didam", "NL"),
    E("Wehl", "Wehl", "NL"),
    E("Doetinchem De Huet", "de Huet", "NL"),
    E("Doetinchem", "Doetinchem", "NL"),
    E("Gaanderen", "Gaanderen", "NL"),
    E("Terborg", "Terborg", "NL"),
    E("Varsseveld", "Varsseveld", "NL"),
    E("Aalten", "Aalten", "NL"),
    E("Winterswijk West", "Winterswijk West", "NL"),
    E("Winterswijk", "Winterswijk", "NL"),
    E("Lichtenvoorde-Groenlo", "Groenlo", "NL"),
    E("Ruurlo", "Ruurlo", "NL"),
    E("Vorden", "Vorden", "NL"),
    E("Lochem", "Lochem", "NL"),
    E("Oosterbeek", "Oosterbeek", "NL"),
    E("Wolfheze", "Wolfheze", "NL"),
    E("Ede-Wageningen", "Ede-Wageningen", "NL"),
    E("Ede Centrum", "Ede Centrum", "NL"),
    E("Lunteren", "Lunteren", "NL"),
    E("Barneveld Centrum", "Barneveld Centrum", "NL"),
    E("Barneveld Zuid", "Barneveld Zuid", "NL"),
    E("Barneveld Noord", "Barneveld Noord", "NL"),
    E("Hoevelaken", "Hoevelaken", "NL"),
    E("Kesteren", "Kesteren", "NL"),
    E("Opheusden", "Opheusden", "NL"),
    E("Hemmen-Dodewaard", "Dodewaard", "NL"),
    E("Zetten-Andelst", "Andelst", "NL"),
    E("Tiel", "Tiel", "NL"),
    E("Tiel Passewaaij", "Tiel Passewaaij", "NL"),
    # Amersfoort en Veluwe
    E("Amersfoort Centraal", "Amersfoort Centraal", "NL", "M"),
    E("Amersfoort Schothorst", "Schothorst", "NL"),
    E("Amersfoort Vathorst", "Vathorst", "NL"),
    E("Nijkerk", "Nijkerk", "NL"),
    E("Putten", "Putten", "NL"),
    E("Ermelo", "Ermelo", "NL"),
    E("Harderwijk", "Harderwijk", "NL"),
    E("Nunspeet", "Nunspeet", "NL"),
    E("'t Harde", "'t Harde", "NL"),
    E("Wezep", "Wezep", "NL"),
    E("Apeldoorn", "Apeldoorn", "NL", "M"),
    E("Apeldoorn Osseveld", "Osseveld", "NL"),
    E("Apeldoorn De Maten", "De Maten", "NL"),
    E("Klarenbeek", "Klarenbeek", "NL"),
    E("Voorst-Empe", "Voorst-Empe", "NL"),
    E("Twello", "Twello", "NL"),
    # Overijssel en Drenthe
    E("Zwolle", "Zwolle", "NL", "M"),
    E("Zwolle Stadshagen", "Zwolle Stadshagen", "NL"),
    E("Kampen", "Kampen", "NL"),
    E("Kampen Zuid", "Kampen Zuid", "NL"),
    E("Dronten", "Dronten", "NL"),
    E("Wijhe", "Wijhe", "NL"),
    E("Olst", "Olst", "NL"),
    E("Deventer", "Deventer", "NL", "M"),
    E("Deventer Colmschate", "Colmschate", "NL"),
    E("Holten", "Holten", "NL"),
    E("Rijssen", "Rijssen", "NL"),
    E("Wierden", "Wierden", "NL"),
    E("Almelo", "Almelo", "NL", "M"),
    E("Almelo de Riet", "de Riet", "NL"),
    E("Vriezenveen", "Vriezenveen", "NL"),
    E("Daarlerveen", "Daarlerveen", "NL"),
    E("Vroomshoop", "Vroomshoop", "NL"),
    E("Dalfsen", "Dalfsen", "NL"),
    E("Ommen", "Ommen", "NL"),
    E("Mariënberg", "Mariënberg", "NL"),
    E("Hardenberg", "Hardenberg", "NL"),
    E("Gramsbergen", "Gramsbergen", "NL"),
    E("Coevorden", "Coevorden", "NL"),
    E("Dalen", "Dalen", "NL"),
    E("Nieuw Amsterdam", "Nieuw Amsterdam", "NL"),
    E("Emmen Zuid", "Emmen Zuid", "NL"),
    E("Emmen", "Emmen", "NL"),
    E("Heino", "Heino", "NL"),
    E("Raalte", "Raalte", "NL"),
    E("Nijverdal", "Nijverdal", "NL"),
    E("Borne", "Borne", "NL"),
    E("Hengelo", "Hengelo", "NL", "M"),
    E("Hengelo Oost", "Hengelo Oost", "NL"),
    E("Hengelo Gezondheidspark", "Hengelo Gezondheidspark", "NL"),
    E("Oldenzaal", "Oldenzaal", "NL"),
    E("Enschede Kennispark", "Enschede Kennispark", "NL"),
    E("Enschede", "Enschede", "NL", "M"),
    E("Enschede De Eschmarke", "Enschede de Eschmarke", "NL"),
    E("Glanerbrug", "Glanerbrug", "NL"),
    E("Goor", "Goor", "NL"),
    E("Delden", "Delden", "NL"),
    E("Steenwijk", "Steenwijk", "NL"),
    E("Meppel", "Meppel", "NL"),
    E("Hoogeveen", "Hoogeveen", "NL"),
    E("Beilen", "Beilen", "NL"),
    E("Assen", "Assen", "NL"),
    # Friesland
    E("Wolvega", "Wolvega", "NL"),
    E("Heerenveen", "Heerenveen", "NL"),
    E("Akkrum", "Akkrum", "NL"),
    E("Grou-Jirnsum", "Grou-Jirnsum", "NL"),
    E("Leeuwarden", "Leeuwarden", "NL", "M"),
    E("Leeuwarden Camminghaburen", "Leeuwarden Camminghaburen", "NL"),
    E("Deinum", "Deinum", "NL"),
    E("Dronryp", "Dronryp", "NL"),
    E("Franeker", "Franeker", "NL"),
    E("Harlingen", "Harlingen", "NL"),
    E("Harlingen Haven", "Harlingen Haven", "NL"),
    E("Mantgum", "Mantgum", "NL"),
    E("Sneek Noord", "Sneek Noord", "NL"),
    E("Sneek", "Sneek", "NL"),
    E("IJlst", "IJlst", "NL"),
    E("Workum", "Workum", "NL"),
    E("Hindeloopen", "Hindeloopen", "NL"),
    E("Koudum-Molkwerum", "Koudum-Molkwerum", "NL"),
    E("Stavoren", "Stavoren", "NL"),
    E("Hurdegaryp", "Hurdegaryp", "NL"),
    E("Feanwâlden", "Feanwâlden", "NL"),
    E("De Westereen", "De Westereen", "NL"),
    E("Buitenpost", "Buitenpost", "NL"),
    # Groningen
    E("Grijpskerk", "Grijpskerk", "NL"),
    E("Zuidhorn", "Zuidhorn", "NL"),
    E("Groningen Noord", "Groningen Noord", "NL"),
    E("Groningen", "Groningen", "NL", "M"),
    E("Groningen Europapark", "Groningen Europapark", "NL"),
    E("Haren", "Haren", "NL"),
    E("Sauwerd", "Sauwerd", "NL"),
    E("Winsum", "Winsum", "NL"),
    E("Bedum", "Bedum", "NL"),
    E("Baflo", "Baflo", "NL"),
    E("Warffum", "Warffum", "NL"),
    E("Usquert", "Usquert", "NL"),
    E("Uithuizen", "Uithuizen", "NL"),
    E("Uithuizermeeden", "Uithuizermeeden", "NL"),
    E("Roodeschool", "Roodeschool", "NL"),
    E("Eemshaven", "Eemshaven", "NL"),
    E("Stedum", "Stedum", "NL"),
    E("Loppersum", "Loppersum", "NL"),
    E("Appingedam", "Appingedam", "NL"),
    E("Delfzijl West", "Delfzijl West", "NL"),
    E("Delfzijl", "Delfzijl", "NL"),
    E("Kropswolde", "Kropswolde", "NL"),
    E("Martenshoek", "Martenshoek", "NL"),
    E("Hoogezand-Sappemeer", "Hoogezand-Sappemeer", "NL"),
    E("Zuidbroek", "Zuidbroek", "NL"),
    E("Veendam", "Veendam", "NL"),
    E("Scheemda", "Scheemda", "NL"),
    E("Winschoten", "Winschoten", "NL"),
    E("Bad Nieuweschans", "Bad Nieuweschans", "NL"),
    # Duitsland
    E("Weener", "Weener", "DE"),
    E("Bunde", "Bunde", "DE", "", "bunde-de", "min_y"),
    E("Ihrhove", "Ihrhove", "DE"),
    E("Leer", "Leer", "DE"),
    E("Bad Bentheim", "Bad Bentheim", "DE"),
    E("Schüttorf", "Schüttorf", "DE"),
    E("Salzbergen", "Salzbergen", "DE"),
    E("Rheine", "Rheine", "DE"),
    E("Hörstel", "Hörstel", "DE"),
    E("Ibbenbüren-Esch", "Ibbenbüren-Esch", "DE"),
    E("Ibbenbüren", "Ibbenbüren", "DE"),
    E("Ibbenbüren-Laggenbeck", "Laggenbeck", "DE"),
    E("Osnabrück Altstadt", "Altstadt", "DE"),
    E("Osnabrück Hbf", "Osnabrück Hbf", "DE"),
    E("Wissingen", "Wissingen", "DE"),
    E("Westerhausen", "Westerhausen", "DE"),
    E("Melle", "Melle", "DE"),
    E("Bruchmühlen", "Bruchmühlen", "DE"),
    E("Bünde (Westfalen)", "Bünde (Westfalen)", "DE"),
    E("Bielefeld Hbf", "Bielefeld Hbf", "DE"),
    E("Hannover Hbf", "Hannover Hbf", "DE"),
    E("Berlin-Spandau", "Berlin-Spandau", "DE"),
    E("Berlin Hbf", "Berlin Hbf", "DE"),
    E("Berlin Ostbahnhof", "Berlin Ostbahnhof", "DE"),
    E("Gronau", "Gronau", "DE"),
    E("Epe (Westf)", "Epe", "DE"),
    E("Ochtrup", "Ochtrup", "DE"),
    E("Metelen Land", "Metelen Land", "DE"),
    E("Ahaus", "Ahaus", "DE"),
    E("Legden", "Legden", "DE"),
    E("Rosendahl-Holtwick", "Holtwick", "DE"),
    E("Coesfeld", "Coesfeld", "DE"),
    E("Lette", "Lette", "DE"),
    E("Dülmen", "Dülmen", "DE"),
    E("Lüdinghausen", "Lüdinghausen", "DE"),
    E("Selm", "Selm", "DE"),
    E("Selm-Beifang", "Selm-Beifang", "DE"),
    E("Steinfurt-Burgsteinfurt", "Burgsteinfurt", "DE"),
    E("Steinfurt-Grottenkamp", "Grottenkamp", "DE"),
    E("Steinfurt-Borghorst", "Borghorst", "DE"),
    E("Nordwalde", "Nordwalde", "DE"),
    E("Altenberge", "Altenberge", "DE"),
    E("Münster-Häger", "Häger", "DE"),
    E("Münster Zentrum Nord", "Zentrum Nord", "DE"),
    E("Münster (Westf) Hbf", "Münster (Westf)", "DE"),
    E("Bork", "Bork", "DE"),
    E("Lünen Hbf", "Lünen Hbf", "DE"),
    E("Lünen-Preußen", "Preußen", "DE"),
    E("Dortmund-Derne", "Dortmund-Derne", "DE"),
    E("Dortmund-Kirchderne", "Kirchderne", "DE"),
    E("Dortmund Hbf", "Dortmund Hbf", "DE"),
    E("Emmerich-Elten", "Emmerich-Elten", "DE"),
    E("Emmerich", "Emmerich", "DE"),
    E("Praest", "Praest", "DE"),
    E("Millingen (b. Rees)", "Millingen", "DE"),
    E("Empel-Rees", "Empel-Rees", "DE"),
    E("Haldern (Rheinland)", "Haldern", "DE"),
    E("Mehrhoog", "Mehrhoog", "DE"),
    E("Wesel-Feldmark", "Wesel-Feldmark", "DE"),
    E("Wesel", "Wesel", "DE"),
    E("Friedrichsfeld", "Friedrichsfeld", "DE"),
    E("Voerde", "Voerde", "DE"),
    E("Dinslaken", "Dinslaken", "DE"),
    E("Oberhausen-Holten", "Oberhausen-Holten", "DE"),
    E("Oberhausen-Sterkrade", "Sterkrade", "DE"),
    E("Oberhausen Hbf", "Oberhausen Hbf", "DE"),
    E("Duisburg Hbf", "Duisburg Hbf", "DE"),
    E("Düsseldorf Flughafen", "Düsseldorf Flughafen", "DE"),
    E("Düsseldorf Hbf", "Düsseldorf Hbf", "DE"),
    E("Neuss Hbf", "Neuss Hbf", "DE"),
    E("Mönchengladbach Hbf", "Mönchengladbach Hbf", "DE"),
    E("Viersen", "Viersen", "DE"),
    E("Dülken", "Dülken", "DE"),
    E("Boisheim", "Boisheim", "DE"),
    E("Breyell", "Breyell", "DE"),
    E("Kaldenkirchen", "Kaldenkirchen", "DE"),
    E("Herzogenrath", "Herzogenrath", "DE"),
    E("Aachen West", "Aachen West", "DE"),
    E("Aachen Hbf", "Aachen Hbf", "DE"),
    E("Wuppertal-Vohwinkel", "Vohwinkel", "DE"),
    E("Wuppertal Hbf", "Wuppertal Hbf", "DE"),
    E("Wuppertal-Barmen", "Wuppertal-Barmen", "DE"),
    E("Wuppertal-Oberbarmen", "Oberbarmen", "DE"),
    E("Schwelm", "Schwelm", "DE"),
    E("Ennepetal", "Ennepetal", "DE"),
    E("Hagen Hbf", "Hagen Hbf", "DE"),
    E("Schwerte (Ruhr)", "Schwerte", "DE"),
    E("Holzwickede", "Holzwickede", "DE"),
    E("Unna", "Unna", "DE"),
    E("Bönen", "Bönen", "DE"),
    E("Hamm (Westf.)", "Hamm", "DE"),
    E("Köln Hbf", "Köln Hbf", "DE"),
    E("Frankfurt (M) Flughafen Fernbhf.", "Fernbhf", "DE"),
    E("Frankfurt (M) Hbf", "Frankfurt (M) Hbf", "DE"),
    E("München Hbf", "München Hbf", "DE"),
    # België
    E("Essen", "Essen", "BE"),
    E("Wildert", "Wildert", "BE"),
    E("Kalmthout", "Kalmthout", "BE"),
    E("Kijkuit", "Kijkuit", "BE"),
    E("Heide", "Heide", "BE"),
    E("Kapellen", "Kapellen", "BE"),
    E("Sint-Mariaburg", "Sint-Mariaburg", "BE"),
    E("Ekeren", "Ekeren", "BE"),
    E("Antwerpen-Noorderdokken", "Noorderdokken", "BE"),
    E("Antwerpen-Luchtbal", "Luchtbal", "BE"),
    E("Antwerpen-Centraal", "Antwerpen-Centraal", "BE"),
    E("Antwerpen-Berchem", "Berchem", "BE"),
    E("Antwerpen-Zuid", "Antwerpen- Zuid", "BE"),
    E("Hoboken-Polder", "Hoboken-Polder", "BE"),
    E("Hemiksem", "Hemiksem", "BE"),
    E("Schelle", "Schelle", "BE"),
    E("Niel", "Niel", "BE"),
    E("Boom", "Boom", "BE"),
    E("Ruisbroek-Sauvegarde", "Sauvegarde", "BE"),
    E("Puurs", "Puurs", "BE"),
    E("Noorderkempen", "Noorderkempen", "BE"),
    E("Mechelen", "Mechelen", "BE"),
    E("Brussels Airport-Zaventem", "Zaventem", "BE"),
    E("Brussel-Noord", "Brussel-Noord", "BE"),
    E("Brussel-Centraal", "Brussel-Centraal", "BE"),
    E("Brussel-Zuid/Midi", "Midi", "BE"),
    E("Visé", "Visé", "BE"),
    E("Bressoux", "Bressoux", "BE"),
    E("Liège-Guillemins", "Guillemins", "BE"),
    # Frankrijk en Verenigd Koninkrijk
    E("Paris Nord", "Paris Nord", "FR"),
    E("Paris Aéroport Roissy Charles-de-Gaulle", "Roissy", "FR"),
    E("Paris Marne-la-Vallée-Chessy", "Chessy", "FR"),
    E("Bourg-St-Maurice", "Bourg-St-Maurice", "FR"),
    E("London St. Pancras International", "Pancras", "GB"),
]


def slug(name):
    s = name.replace("ß", "ss")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def norm_word(w):
    return w.lower().replace("’", "'").strip(".,;")


def word_matches(kw, w):
    if len(kw) <= 4:
        return kw == w
    return kw in w


def overlaps(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return (ix * iy) / area > 0.5


def find_hits(kwords, words, claimed):
    hits = []
    n = len(kwords)
    for i in range(len(words) - n + 1):
        if all(word_matches(kwords[j], words[i + j][1]) for j in range(n)):
            rects = [words[i + j][0] for j in range(n)]
            if any(overlaps(r, c) for r in rects for c in claimed):
                continue
            hits.append(rects)
    return hits


def union_center(rects):
    x0 = min(r[0] for r in rects)
    y0 = min(r[1] for r in rects)
    x1 = max(r[2] for r in rects)
    y1 = max(r[3] for r in rects)
    return [round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)]


def main():
    doc = fitz.open(PDF)
    pages = {}
    for pno in range(min(4, doc.page_count)):
        raw = doc[pno].get_text("words")
        pages[pno + 1] = [((w[0], w[1], w[2], w[3]), norm_word(w[4])) for w in raw]

    ids = set()
    entries = []
    for name, key, country, flags, ident, picker in STATIONS:
        sid = ident or slug(name)
        if sid in ids:
            raise SystemExit(f"FAIL: duplicate id '{sid}' for '{name}', add an id override")
        ids.add(sid)
        entries.append(
            {
                "id": sid,
                "name": name,
                "key": [norm_word(k) for k in key.split()],
                "printed": key,
                "country": country,
                "major": "M" in flags,
                "suspect": "S" in flags,
                "picker": picker,
            }
        )

    entries.sort(key=lambda e: sum(len(k) for k in e["key"]), reverse=True)
    claimed = {p: [] for p in pages}
    coords = {e["id"]: {} for e in entries}
    multi = []
    for e in entries:
        for p, words in pages.items():
            hits = find_hits(e["key"], words, claimed[p])
            if not hits:
                # Rotated labels fragment in the word list; search_for handles them.
                rects = [
                    (r.x0, r.y0, r.x1, r.y1)
                    for r in doc[p - 1].search_for(e["printed"])
                ]
                rects = [
                    r for r in rects if not any(overlaps(r, c) for c in claimed[p])
                ]
                hits = [[r] for r in rects]
            if not hits:
                continue
            if len(hits) > 1:
                multi.append((e["id"], p, len(hits)))
                if e["picker"] == "min_y":
                    hits.sort(key=lambda rects: rects[0][1])
                elif e["picker"] == "max_y":
                    hits.sort(key=lambda rects: -rects[0][1])
            chosen = hits[0]
            claimed[p].extend(chosen)
            coords[e["id"]][str(p)] = union_center(chosen)

    stations = []
    for e in sorted(entries, key=lambda e: e["id"]):
        st = {
            "id": e["id"],
            "name": e["name"],
            "nameAsPrinted": e["printed"],
            "country": e["country"],
            "major": e["major"],
            "suspect": e["suspect"],
        }
        if coords[e["id"]]:
            st["coords"] = coords[e["id"]]
        stations.append(st)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"schemaVersion": 1, "source": SOURCE, "stations": stations},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )

    total = len(stations)
    full = sum(1 for e in entries if len(coords[e["id"]]) == 4)
    partial = sum(1 for e in entries if 0 < len(coords[e["id"]]) < 4)
    zero = [e["id"] for e in entries if not coords[e["id"]]]
    print(f"OK wrote {OUT} with {total} stations")
    print(f"coords: {full} on all 4 pages, {partial} partial, {len(zero)} zero hits")
    if zero:
        print("zero-hit stations (verify these):")
        for z in zero:
            print(f"  {z}")
    if multi:
        print(f"multi-hit picks: {len(multi)} (first hit or picker used)")


if __name__ == "__main__":
    main()
