#!/usr/bin/python2.6
#
# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2010  Joanna Rutkowska <joanna@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
#

import sys
from PyQt4.QtCore import *
from PyQt4.QtGui import *

from qubes.qubes import QubesVmCollection
from qubes.qubes import QubesException
from qubes.qubes import qubes_store_filename
from qubes.qubes import QubesVmLabels
from qubes.qubes import dry_run
from qubes.qubes import qubes_guid_path
from qubes.qubes import QubesDaemonPidfile

import qubesmanager.qrc_resources
import ui_newappvmdlg

from pyinotify import WatchManager, Notifier, ThreadedNotifier, EventsCodes, ProcessEvent

import subprocess
import time
import threading

class QubesConfigFileWatcher(ProcessEvent):
    def __init__ (self, update_func):
        self.update_func = update_func
        pass
    
    def process_IN_CLOSE_WRITE (self, event):
        self.update_func()

class VmStatusIcon(QLabel):
    def __init__(self, vm, parent=None):
        super (VmStatusIcon, self).__init__(parent)
        self.vm = vm
        (icon_pixmap, icon_sz) = self.set_vm_icon(self.vm)
        self.setPixmap (icon_pixmap)
        self.setFixedSize (icon_sz)
        self.previous_power_state = vm.is_running()

    def update(self):
        if self.previous_power_state != self.vm.is_running():
            (icon_pixmap, icon_sz) = self.set_vm_icon(self.vm)
            self.setPixmap (icon_pixmap)
            self.setFixedSize (icon_sz)
            self.previous_power_state = self.vm.is_running()

    def set_vm_icon(self, vm):
        if vm.qid == 0:
            icon = QIcon (":/dom0.png")
        elif vm.is_appvm():
            icon = QIcon (vm.label.icon_path)
        elif vm.is_templete():
            icon = QIcon (":/templatevm.png")
        elif vm.is_netvm():
            icon = QIcon (":/netvm.png")
        else:
            icon = QIcon()

        icon_sz = QSize (VmManagerWindow.row_height * 0.8, VmManagerWindow.row_height * 0.8)
        if vm.is_running():
            icon_pixmap = icon.pixmap(icon_sz)
        else:
            icon_pixmap = icon.pixmap(icon_sz, QIcon.Disabled)

        return (icon_pixmap, icon_sz)


class VmInfoWidget (QWidget):

    def __init__(self, vm, parent = None):
        super (VmInfoWidget, self).__init__(parent)

        layout0 = QHBoxLayout()

        label_name = QLabel (vm.name)

        self.vm_running = vm.is_running()
        layout0.addWidget(label_name, alignment=Qt.AlignLeft)

        layout1 = QHBoxLayout()

        if vm.is_appvm():
            label_tmpl = QLabel ("<i><font color=\"gray\">" + vm.template_vm.name + "</i></font>")
        elif vm.is_templete():
            label_tmpl = QLabel ("<i><font color=\"gray\">TemplateVM</i></font>")
        elif vm.qid == 0:
            label_tmpl = QLabel ("<i><font color=\"gray\">AdminVM</i></font>")
        elif vm.is_netvm():
            label_tmpl = QLabel ("<i><font color=\"gray\">NetVM</i></font>")
        else:
            label_tmpl = QLabel ("")

        label_icon_networked = self.set_icon(":/networking.png", vm.is_networked())
        layout1.addWidget(label_icon_networked, alignment=Qt.AlignLeft)

        if vm.is_updateable():
            label_icon_updtbl = self.set_icon(":/updateable.png", True)
            layout1.addWidget(label_icon_updtbl, alignment=Qt.AlignLeft)

        layout1.addWidget(label_tmpl, alignment=Qt.AlignLeft)

        layout1.addStretch()

        layout2 = QVBoxLayout ()
        layout2.addLayout(layout0)
        layout2.addLayout(layout1)

        layout3 = QHBoxLayout ()
        self.vm_icon = VmStatusIcon(vm)
        layout3.addWidget(self.vm_icon)
        layout3.addSpacing (10)
        layout3.addLayout(layout2)

        self.setLayout(layout3)

    def set_icon(self, icon_path, enabled = True):
        label_icon = QLabel()
        icon = QIcon (icon_path)
        icon_sz = QSize (VmManagerWindow.row_height * 0.3, VmManagerWindow.row_height * 0.3)
        icon_pixmap = icon.pixmap(icon_sz, QIcon.Disabled if not enabled else QIcon.Normal)
        label_icon.setPixmap (icon_pixmap)
        label_icon.setFixedSize (icon_sz)
        return label_icon

    def update_vm_state (self, vm):
        self.vm_icon.update()

class LoadChartWidget (QWidget):

    def __init__(self, vm, parent = None):
        super (LoadChartWidget, self).__init__(parent)
        self.load = vm.get_cpu_total_load() if vm.is_running() else 0
        assert self.load >= 0 and self.load <= 100, "load = {0}".format(self.load)
        self.load_history = [self.load]

    def update_load (self, vm):
        self.load = vm.get_cpu_total_load() if vm.is_running() else 0
        assert self.load >= 0 and self.load <= 100, "load = {0}".format(self.load)
        self.load_history.append (self.load)
        self.repaint()

    def paintEvent (self, Event = None):
        p = QPainter (self)
        dx = 4

        W = self.width() 
        H = self.height() - 5
        N = len(self.load_history)
        if N > W/dx:
            tail = N - W/dx
            N = W/dx
            self.load_history = self.load_history[tail:]

        assert len(self.load_history) == N

        for i in range (0, N-1):
            val = self.load_history[N- i - 1]
            hue = 200
            sat = 70 + val*(255-70)/100
            color = QColor.fromHsv (hue, sat, 255)
            pen = QPen (color)
            pen.setWidth(dx-1)
            p.setPen(pen)
            if val > 0:
                p.drawLine (W - i*dx - dx, H , W - i*dx - dx, H - (H - 5) * val/100)

class VmRowInTable(object):
    def __init__(self, vm, row_no, table):
        self.vm = vm
        self.row_no = row_no

        table.setRowHeight (row_no, VmManagerWindow.row_height)

        self.info_widget = VmInfoWidget(vm)
        table.setCellWidget(row_no, 0, self.info_widget)

        self.load_widget = LoadChartWidget(vm)
        table.setCellWidget(row_no, 1, self.load_widget)

    def update(self, counter):
        self.info_widget.update_vm_state(self.vm)
        if counter % 3 == 0:
            self.load_widget.update_load(self.vm)

class NewAppVmDlg (QDialog, ui_newappvmdlg.Ui_NewAppVMDlg):
    def __init__(self, parent = None):
        super (NewAppVmDlg, self).__init__(parent)
        self.setupUi(self)

vm_shutdown_timeout = 15000 # in msec

class VmShutdownMonitor(QObject):
    def __init__(self, vm):
        self.vm = vm

    def check_if_vm_has_shutdown(self):
        vm = self.vm
        if not vm.is_running():
            return

        reply = QMessageBox.question(None, "VM Shutdown", 
                                     "The VM <b>'{0}'</b> hasn't shutdown within the last {1} seconds, do you want to kill it?<br>".format(vm.name, vm_shutdown_timeout/1000),
                                     "Kill it!", "Wait another {0} seconds...".format(vm_shutdown_timeout/1000))

        if reply == 0:
            vm.force_shutdown()
        else:
            QTimer.singleShot (vm_shutdown_timeout, self.check_if_vm_has_shutdown)

class ThreadMonitor(QObject):
    def __init__(self):
        self.success = True
        self.error_msg = None
        self.event_finished = threading.Event()

    def set_error_msg(self, error_msg):
        self.success = False
        self.error_msg = error_msg
        self.set_finished()

    def is_finished(self):
        return self.event_finished.is_set()

    def set_finished(self):
        self.event_finished.set()


class VmManagerWindow(QMainWindow):
    columns_widths = [200, 150]
    row_height = 50
    max_visible_rows = 14
    update_interval = 1000 # in msec
    show_inactive_vms = True

    def __init__(self, parent=None):
        super(VmManagerWindow, self).__init__(parent)


        self.action_createvm = self.createAction ("Create AppVM", slot=self.create_appvm,
                                             icon="createvm", tip="Create a new AppVM")

        self.action_removevm = self.createAction ("Remove AppVM", slot=self.remove_appvm,
                                             icon="removevm", tip="Remove an existing AppVM (must be stopped first)")

        self.action_resumevm = self.createAction ("Start/Resume VM", slot=self.resume_vm,
                                             icon="resumevm", tip="Start/Resusme a VM")

        self.action_pausevm = self.createAction ("Pause VM", slot=self.pause_vm,
                                             icon="pausevm", tip="Pause a running VM")

        self.action_shutdownvm = self.createAction ("Shutdown VM", slot=self.shutdown_vm,
                                             icon="shutdownvm", tip="Shutdown a running VM")

        self.action_updatevm = self.createAction ("Update VM", slot=None,
                                             icon="updateable", tip="Update VM (only for 'updateable' VMs, e.g. templates)")

        self.action_showallvms = self.createAction ("Show/Hide Inactive VMs", slot=None, checkable=True,
                                             icon="showallvms", tip="Show/Hide Inactive VMs")

        self.action_showcpuload = self.createAction ("Show/Hide CPU Load chart", slot=self.showcpuload, checkable=True,
                                             icon="showcpuload", tip="Show/Hide CPU Load chart")


        self.action_removevm.setDisabled(True)
        self.action_resumevm.setDisabled(True)
        self.action_pausevm.setDisabled(True)
        self.action_shutdownvm.setDisabled(True)
        self.action_updatevm.setDisabled(True)

        self.action_showcpuload.setDisabled(True)

        self.toolbar = self.addToolBar ("Toolbar")
        self.toolbar.setFloatable(False)
        self.addActions (self.toolbar, (self.action_createvm, self.action_removevm,
                                   None,
                                   self.action_resumevm, self.action_pausevm, self.action_shutdownvm, self.action_updatevm,
                                   None,
                                   self.action_showcpuload,
                                   ))
        
        self.table = QTableWidget()
        self.setCentralWidget(self.table)
        self.table.clear()
        self.table.setColumnCount(len(VmManagerWindow.columns_widths))
        for (col, width) in enumerate (VmManagerWindow.columns_widths):
            self.table.setColumnWidth (col, width)

        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().hide()
        self.table.setGridStyle(Qt.NoPen)
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
 
        self.qvm_collection = QubesVmCollection()
        self.setWindowTitle("Qubes VM Manager")
 
        self.connect(self.table, SIGNAL("itemSelectionChanged()"), self.table_selection_changed)

        self.fill_table()

        tbl_W = 0
        for (i, w) in enumerate(VmManagerWindow.columns_widths):
            tbl_W += w

        # TODO: '6' -- WTF?!
        tbl_H = self.toolbar.height() + 6 + \
                self.table.horizontalHeader().height() + 6

        n = self.table.rowCount();
        if n > VmManagerWindow.max_visible_rows:
            n = VmManagerWindow.max_visible_rows
        for i in range (0, n):
            tbl_H += self.table.rowHeight(i)

        self.setMinimumWidth(tbl_W)
        self.setGeometry(self.x(), self.y(), self.x() + tbl_W, self.y() + tbl_H)

        self.counter = 0
        self.shutdown_monitor = {}
        QTimer.singleShot (self.update_interval, self.update_table)

    def addActions(self, target, actions):
        for action in actions:
            if action is None:
                target.addSeparator()
            else:
                target.addAction(action)


    def createAction(self, text, slot=None, shortcut=None, icon=None,
                     tip=None, checkable=False, signal="triggered()"):
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(QIcon(":/%s.png" % icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            self.connect(action, SIGNAL(signal), slot)
        if checkable:
            action.setCheckable(True)
        return action


    def get_vms_list(self):
        self.qvm_collection.lock_db_for_reading()
        self.qvm_collection.load()
        self.qvm_collection.unlock_db()

        if self.show_inactive_vms:
            vms_list = [vm for vm in self.qvm_collection.values()]
        else:
            vms_list = [vm for vm in self.qvm_collection.values() if vm.is_running()]

        no_vms = len (vms_list)
        vms_to_display = []

        # First, the NetVMs...
        for netvm in vms_list:
            if netvm.is_netvm():
                vms_to_display.append (netvm)

        # Now, the templates...
        for tvm in vms_list:
            if tvm.is_templete():
                vms_to_display.append (tvm)

        label_list = QubesVmLabels.values()
        label_list.sort(key=lambda l: l.index)
        for label in [label.name for label in label_list]:
            for appvm in [vm for vm in vms_list if (vm.is_appvm() and vm.label.name == label)]:
                vms_to_display.append(appvm)

        assert len(vms_to_display) == no_vms
        return vms_to_display

    def fill_table(self):
        self.table.clear()
        vms_list = self.get_vms_list()
        self.table.setRowCount(len(vms_list))

        vms_in_table = []

        for (row_no, vm) in enumerate(vms_list):
            vm_row = VmRowInTable (vm, row_no, self.table)
            vms_in_table.append (vm_row)

        self.vms_list = vms_list
        self.vms_in_table = vms_in_table
        self.reload_table = False


    def mark_table_for_update(self):
        self.reload_table = True

    # When calling update_table() directly, always use out_of_schedule=True!
    def update_table(self, out_of_schedule=False):
        if self.reload_table:
            self.fill_table()

        for vm_row in self.vms_in_table:
            vm_row.update(self.counter)

        self.table_selection_changed()

        if not out_of_schedule:
            self.counter += 1
            QTimer.singleShot (self.update_interval, self.update_table)


    def table_selection_changed (self):
        vm = self.get_selected_vm()

        # Update available actions:

        self.action_removevm.setEnabled(not vm.installed_by_rpm and not vm.is_running())
        #self.action_resumevm.setEnabled(not vm.is_running())
        #self.action_pausevm.setEnabled(vm.is_running() and vm.qid != 0)
        self.action_shutdownvm.setEnabled(vm.is_running() and vm.qid != 0)

    def closeEvent (self, event):
        self.hide()
        event.ignore()

    def create_appvm(self):
        dialog = NewAppVmDlg()


        # Theoretically we should be locking for writing here and unlock
        # only after the VM creation finished. But the code would be more messy...
        # Instead we lock for writing in the actual worker thread

        self.qvm_collection.lock_db_for_reading()
        self.qvm_collection.load()
        self.qvm_collection.unlock_db()

        label_list = QubesVmLabels.values()
        label_list.sort(key=lambda l: l.index)
        for (i, label) in enumerate(label_list):
            dialog.vmlabel.insertItem(i, label.name)
            dialog.vmlabel.setItemIcon (i, QIcon(label.icon_path))

        template_vm_list = [vm for vm in self.qvm_collection.values() if vm.is_templete()]

        default_index = 0
        for (i, vm) in enumerate(template_vm_list):
            if vm is self.qvm_collection.get_default_template_vm():
                default_index = i
                dialog.template_name.insertItem(i, vm.name + " (default)")
            else:
                dialog.template_name.insertItem(i, vm.name)
        dialog.template_name.setCurrentIndex(default_index)

        dialog.vmname.selectAll()
        dialog.vmname.setFocus()

        if dialog.exec_():
            vmname = str(dialog.vmname.text())
            if self.qvm_collection.get_vm_by_name(vmname) is not None:
                QMessageBox.warning (None, "Incorrect AppVM Name!", "A VM with the name <b>{0}</b> already exists in the system!".format(vmname))
                return

            label = label_list[dialog.vmlabel.currentIndex()]
            template_vm = template_vm_list[dialog.template_name.currentIndex()]

            thread_monitor = ThreadMonitor()
            thread = threading.Thread (target=self.do_create_appvm, args=(vmname, label, template_vm, thread_monitor))
            thread.daemon = True
            thread.start()

            progress = QProgressDialog ("Creating new AppVM <b>{0}</b>...".format(vmname), "", 0, 0)
            progress.setCancelButton(None)
            progress.setModal(True)
            progress.show()
            
            while not thread_monitor.is_finished():
                app.processEvents()
                time.sleep (0.1)

            progress.hide()

            if thread_monitor.success:
                trayIcon.showMessage ("Qubes Manager", "VM '{0}' has been created.".format(vmname), msecs=3000)
            else:
                QMessageBox.warning (None, "Error creating AppVM!", "ERROR: {0}".format(thread_monitor.error_msg))


    def do_create_appvm (self, vmname, label, template_vm, thread_monitor):
        try:
            self.qvm_collection.lock_db_for_writing()
            self.qvm_collection.load()

            vm = self.qvm_collection.add_new_appvm(vmname, template_vm, label = label)
            vm.create_on_disk(verbose=False)
            vm.add_to_xen_storage()
            self.qvm_collection.save()
        except Exception as ex:
            thread_monitor.set_error_msg (str(ex))
            vm.remove_from_disk()
        finally:
            self.qvm_collection.unlock_db()

        thread_monitor.set_finished()


    def get_selected_vm(self):
        row_index = self.table.currentRow()
        assert self.vms_in_table[row_index] is not None
        vm = self.vms_in_table[row_index].vm
        return vm

    def remove_appvm(self):
        vm = self.get_selected_vm()
        assert not vm.is_running()
        assert not vm.installed_by_rpm

        self.qvm_collection.lock_db_for_reading()
        self.qvm_collection.load()
        self.qvm_collection.unlock_db()
 
        if vm.is_templete():
            dependent_vms = self.qvm_collection.get_vms_based_on(vm.qid)
            if len(dependent_vms) > 0:
                QMessageBox.warning (None, "Warning!", 
                                     "This Template VM cannot be removed, because there is at least one AppVM that is based on it.<br>"
                                     "<small>If you want to remove this Template VM and all the AppVMs based on it,"
                                     "you should first remove each individual AppVM that uses this template.</small>")

                return

        reply = QMessageBox.question(None, "VM Removal Confirmation", 
                                     "Are you sure you want to remove the VM <b>'{0}'</b>?<br>"
                                     "<small>All data on this VM's private storage will be lost!</small>".format(vm.name),
                                     QMessageBox.Yes | QMessageBox.Cancel)


        if reply == QMessageBox.Yes:

            thread_monitor = ThreadMonitor()
            thread = threading.Thread (target=self.do_remove_vm, args=(vm, thread_monitor))
            thread.daemon = True
            thread.start()

            progress = QProgressDialog ("Removing VM: <b>{0}</b>...".format(vm.name), "", 0, 0)
            progress.setCancelButton(None)
            progress.setModal(True)
            progress.show()
            
            while not thread_monitor.is_finished():
                app.processEvents()
                time.sleep (0.1)

            progress.hide()

            if thread_monitor.success:
                trayIcon.showMessage ("Qubes Manager", "VM '{0}' has been removed.".format(vm.name), msecs=3000)
            else:
                QMessageBox.warning (None, "Error removing M!", "ERROR: {0}".format(thread_monitor.error_msg))

    def do_remove_vm (self, vm, thread_monitor):
        try:
            self.qvm_collection.lock_db_for_writing()
            self.qvm_collection.load()

            #TODO: the following two conditions should really be checked by qvm_collection.pop() overload...
            if vm.is_templete() and qvm_collection.default_template_qid == vm.qid:
                qvm_collection.default_template_qid = None
            if vm.is_netvm() and qvm_collection.default_netvm_qid == vm.qid:
                qvm_collection.default_netvm_qid = None

            vm.remove_from_xen_storage()
            vm.remove_from_disk()
            self.qvm_collection.pop(vm.qid)
            self.qvm_collection.save()
        except Exception as ex:
            thread_monitor.set_error_msg (str(ex))
        finally:
            self.qvm_collection.unlock_db()

        thread_monitor.set_finished()

    def resume_vm(self):
        pass
 
    def pause_vm(self):
        pass

    def shutdown_vm(self):
        vm = self.get_selected_vm()
        assert vm.is_running()

        reply = QMessageBox.question(None, "VM Shutdown Confirmation", 
                                     "Are you sure you want to power down the VM <b>'{0}'</b>?<br>"
                                     "<small>This will shutdown all the running applications within this VM.</small>".format(vm.name),
                                     QMessageBox.Yes | QMessageBox.Cancel)

        app.processEvents()

        if reply == QMessageBox.Yes:
            try:
                subprocess.check_call (["/usr/sbin/xm", "shutdown", vm.name])
            except Exception as ex:
                QMessageBox.warning (None, "Error shutting down VM!", "ERROR: {0}".format(ex))
                return

            trayIcon.showMessage ("Qubes Manager", "VM '{0}' is shutting down...".format(vm.name), msecs=3000)
            self.shutdown_monitor[vm.qid] = VmShutdownMonitor (vm)
            QTimer.singleShot (vm_shutdown_timeout, self.shutdown_monitor[vm.qid].check_if_vm_has_shutdown)

    def showcpuload(self):
        pass

                   
class QubesTrayIcon(QSystemTrayIcon):
    def __init__(self, icon):
        QSystemTrayIcon.__init__(self, icon)
        self.menu = QMenu()

        action_showmanager = self.createAction ("Open VM Manager", slot=show_manager, icon="qubes")
        action_backup = self.createAction ("Make backup")
        action_preferences = self.createAction ("Preferences")
        action_set_netvm = self.createAction ("Set default NetVM", icon="networking")
        action_sys_info = self.createAction ("System Info", icon="dom0")
        action_exit = self.createAction ("Exit", slot=exit_app)

        action_backup.setDisabled(True)
        action_preferences.setDisabled(True)
        action_set_netvm.setDisabled(True)
        action_sys_info.setDisabled(True)

        self.addActions (self.menu, (action_showmanager, action_backup, action_sys_info, None, action_preferences, action_set_netvm, None, action_exit))

        self.setContextMenu(self.menu)

        self.connect (self, SIGNAL("activated (QSystemTrayIcon::ActivationReason)"), self.icon_clicked)

    def icon_clicked(self, reason):
        if reason == QSystemTrayIcon.Context:
            # Handle the right click normally, i.e. display the context menu
            return
        else:
            show_manager()

    def addActions(self, target, actions):
        for action in actions:
            if action is None:
                target.addSeparator()
            else:
                target.addAction(action)


    def createAction(self, text, slot=None, shortcut=None, icon=None,
                     tip=None, checkable=False, signal="triggered()"):
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(QIcon(":/%s.png" % icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            self.connect(action, SIGNAL(signal), slot)
        if checkable:
            action.setCheckable(True)
        return action


def show_manager():
    manager_window.show()


def exit_app():
    notifier.stop()
    app.exit()


# Bases on the original code by:
# Copyright (c) 2002-2007 Pascal Varet <p.varet@gmail.com>

def handle_exception( exc_type, exc_value, exc_traceback ):
    import sys
    import os.path
    import traceback

    filename, line, dummy, dummy = traceback.extract_tb( exc_traceback ).pop()
    filename = os.path.basename( filename )
    error    = "%s: %s" % ( exc_type.__name__, exc_value )

    QMessageBox.critical(None, "Houston, we have a problem...",
                         "Whoops. A critical error has occured. This is most likely a bug "
                         "in Qubes Manager.<br><br>"
                         "<b><i>%s</i></b>" % error +
                         "at <b>line %d</b> of file <b>%s</b>.<br/><br/>"
                         % ( line, filename ))

    #sys.exit(1)

def main():


    # Avoid starting more than one instance of the app
    lock = QubesDaemonPidfile ("qubes-manager")
    if lock.pidfile_exists():
        if lock.pidfile_is_stale():
            lock.remove_pidfile()
            print "Removed stale pidfile (has the previous daemon instance crashed?)."
        else:
            exit (0)

    lock.create_pidfile()

    global app
    app = QApplication(sys.argv)
    app.setOrganizationName("The Qubes Project")
    app.setOrganizationDomain("http://qubes-os.org")
    app.setApplicationName("Qubes VM Manager")
    app.setWindowIcon(QIcon(":/qubes.png"))

    sys.excepthook = handle_exception

    global manager_window
    manager_window = VmManagerWindow()
    wm = WatchManager()
    mask = EventsCodes.OP_FLAGS.get('IN_CLOSE_WRITE')

    global notifier
    notifier = ThreadedNotifier(wm, QubesConfigFileWatcher(manager_window.mark_table_for_update))
    notifier.start()
    wdd = wm.add_watch(qubes_store_filename, mask)

    global trayIcon
    trayIcon = QubesTrayIcon(QIcon(":/qubes.png"))
    trayIcon.show()

    app.exec_()
    trayIcon = None
