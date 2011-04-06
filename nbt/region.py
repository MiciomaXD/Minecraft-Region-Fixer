from nbt import NBTFile
from chunk import Chunk
from struct import pack, unpack
from gzip import GzipFile
import zlib
from StringIO import StringIO
import math, time, datetime
from os.path import getsize

class RegionHeaderError(Exception):
	"""Error in the header of the region file for a given chunk"""
	def __init__(self, msg):
		self.msg = msg

class ChunkDataError(Exception):
	"""Error in the data of a chunk, included the bytes of lenght and byte version"""
	def __init__(self, msg):
		self.msg = msg
		

class RegionFile(object):
	"""
	A convenience class for extracting NBT files from the Minecraft Beta Region Format
	"""
	
	def __init__(self, filename=None, fileobj=None):
		if filename:
			self.filename = filename
			self.file = open(filename, 'r+b')
		if fileobj:
			self.file = fileobj
		self.chunks = []
		self.header = {}
		self.extents = None
		if self.file:
			self.parse_header()

	def __del__(self):
		if self.file:
			self.file.close()

	def parse_header(self):
		for index in range(0,4100,4):
			self.file.seek(index)
			offset, length = unpack(">IB", "\0"+self.file.read(4))
			if offset:
				x = (index/4) % 32
				z = int(index/4)/32
				self.header[x,z] = (offset,length,0)
		print self.header
	
	def get_chunks(self):
		index = 0
		self.file.seek(index)
		chunks = []
		while (index < 4096):
			offset, length = unpack(">IB", "\0"+self.file.read(4))
			if offset:
				x = (index/4) % 32
				z = int(index/4)/32
				chunks.append(Chunk(x,z,length))
			index += 4
		return chunks
	
	@classmethod
	def getchunk(path, x, z):
		pass
		
	def get_timestamp(self, x, z):
		self.file.seek(4096+4*(x+z*32))
		timestamp = unpack(">I",self.file.read(4))

	def get_chunk(self, x, z):
		#read metadata block
		block = 4*(x+z*32)
		self.file.seek(block)
		offset, length = unpack(">IB", "\0"+self.file.read(4))
		offset = offset * 1024*4 # offset is in 4KiB sectors
		if offset >= getsize(self.filename) - 1024*4: # mininmun chunk size = 1 sector
			raise RegionHeaderError('The offset of the chunk is outside the file')

		if offset:
			self.file.seek(offset)
			length = unpack(">I", self.file.read(4))
			length = length[0] # For some reason, this is coming back as a tuple
			if length == 0: # no chunk can be 0 length!
				raise ChunkDataError('The length of the chunk is 0')

			if length > 32768 + 16384 + 16384 + 16384 + 256 + 1024: 
			# aprox size of an uncompressed chunk: blocks + data + skylight + block light + heightmap + entities(~1024?)
			# also a chunk can't be bigger than 1MB
				raise ChunkDataError('The length of the chunk is too big')

			compression = unpack(">B", self.file.read(1))
			compression = compression[0]
			chunk = self.file.read(length-1)
			if (compression == 2):
				chunk = zlib.decompress(chunk)
				chunk = StringIO(chunk)
				return NBTFile(buffer=chunk) #pass uncompressed
			else:
				chunk = StringIO(chunk)
				return NBTFile(fileobj=chunk) #pass compressed; will be filtered through Gzip
		else:
			return None
	
	def write_chunk(self, x, z, nbt_file):
		""" A smart chunk writer that uses extents to trade off between fragmentation and cpu time"""
		data = StringIO()
		nbt_file.write_file(buffer = data) #render to buffer; uncompressed
		
		compressed = zlib.compress(data.getvalue()) #use zlib compression, rather than Gzip
		data = StringIO(compressed)
		
		nsectors = int(math.ceil((data.len+0.001)/4096))
		
		#if it will fit back in it's original slot:
		self.file.seek(4*(x+z*32))
		offset, length = unpack(">IB", "\0"+self.file.read(4))
		pad_end = False
		if (offset == 0 and length == 0):
			# This chunk hasn't been generated yet
			# This chunk should just be appended to the end of the file
			self.file.seek(0,2) # go to the end of the file
			file_length = self.file.tell()-1 # current offset is file length
			total_sectors = file_length/4096
			sector = total_sectors+1
			pad_end = True
		else:
			if nsectors <= length:
				sector = offset
			else:
				#traverse extents to find first-fit
				sector= 2 #start at sector 2, first sector after header
				while 1:
					#check if extent is used, else move foward in extent list by extent length
					self.file.seek(0)
					found = True
					for intersect_offset, intersect_len in ( (extent_offset, extent_len)
						for extent_offset, extent_len in (unpack(">IB", "\0"+self.file.read(4)) for block in xrange(1024))
							if extent_offset != 0 and ( sector >= extent_offset < (sector+nsectors))):
								#move foward to end of intersect
								sector = intersect_offset + intersect_len
								found = False
								break
					if found:
						break

		#write out chunk to region
		self.file.seek(sector*4096)
		self.file.write(pack(">I", data.len+1)) #length field
		self.file.write(pack(">B", 2)) #compression field
		self.file.write(data.getvalue()) #compressed data
		if pad_end:
			# Write zeros up to the end of the chunk
			self.file.seek((sector+nsectors)*4096-1)
			self.file.write(chr(0))
		
		#seek to header record and write offset and length records
		self.file.seek(4*(x+z*32))
		self.file.write(pack(">IB", sector, nsectors)[1:])
		
		#write timestamp
		self.file.seek(4096+4*(x+z*32))
		timestamp = time.mktime(datetime.datetime.now().timetuple())
		self.file.write(pack(">I", timestamp))
